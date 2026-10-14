from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from education.tests import test_lesson_generation as fixtures
from education.lesson_generation import generate_lessons
from education.models import Lesson
from users.models import User


class LessonAdminTests(TestCase):
    def setUp(self):
        fixtures.LessonGenerationTests.setUp(self)
        self.admin_user = User.objects.create_superuser(username="admin", full_name="Admin", password="pass")
        self.client.force_login(self.admin_user)
        generate_lessons(self.day, 1, apply=True)
        self.lesson = Lesson.objects.get()

    def data(self, **changes):
        return dict(schedule=self.schedule.pk, teacher=self.teacher.pk, subject=self.subject.pk,
            starts_at_0=self.day.isoformat(), starts_at_1="18:30:00",
            ends_at_0=self.day.isoformat(), ends_at_1="19:30:00",
            status="planned", room="A", cancelled_reason="", **changes)

    def post(self, data, lesson=None):
        url = reverse("admin:education_lesson_change", args=[lesson.pk]) if lesson else reverse("admin:education_lesson_add")
        return self.client.post(url, data)

    def test_teacher_overlap_shows_error_without_saving(self):
        data = self.data(); data["room"] = "B"
        response = self.post(data)
        self.assertContains(response, "Пересечение с занятием")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_room_overlap_with_other_teacher_is_rejected(self):
        data = self.data(); data["teacher"] = User.objects.create_user(full_name="Other").pk
        self.assertContains(self.post(data), "кабинет уже занят")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_adjacent_lesson_saves(self):
        data = self.data(); data.update(starts_at_1="19:00:00", ends_at_1="20:00:00")
        self.assertEqual(self.post(data).status_code, 302)
        self.assertEqual(Lesson.objects.count(), 2)

    def test_unchanged_lesson_does_not_conflict_with_itself(self):
        data = self.data(); data.update(starts_at_1="18:00:00", ends_at_1="19:00:00")
        self.assertEqual(self.post(data, self.lesson).status_code, 302)

    def test_cancellation_allowed_but_restoration_blocked(self):
        data = self.data(); data["status"] = "cancelled"
        self.assertEqual(self.post(data).status_code, 302)
        cancelled = Lesson.objects.exclude(pk=self.lesson.pk).get()
        data["status"] = "planned"
        self.assertContains(self.post(data, cancelled), "Пересечение с занятием")
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "cancelled")

    def test_invalid_interval_shows_form_error(self):
        data = self.data(); data["ends_at_1"] = "17:00:00"
        self.assertContains(self.post(data), "Окончание должно быть позже начала")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_failed_move_preserves_original_record(self):
        data = self.data(); data.update(starts_at_1="20:00:00", ends_at_1="21:00:00")
        self.assertEqual(self.post(data).status_code, 302)
        other = Lesson.objects.exclude(pk=self.lesson.pk).get()
        before = other.starts_at
        self.assertContains(self.post(self.data(), other), "Пересечение с занятием")
        other.refresh_from_db()
        self.assertEqual(other.starts_at, before)


class ConcurrentLessonAdminTests(TransactionTestCase):
    def test_admin_and_generator_cannot_book_shared_room(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        fixtures.LessonGenerationTests.setUp(self)
        extra = fixtures.LessonGenerationTests.extra_schedule(self, other_teacher=True)
        admin_user = User.objects.create_superuser(username="admin", full_name="Admin", password="pass")
        client = Client(); client.force_login(admin_user)
        barrier = Barrier(2)

        def run(mode):
            try:
                barrier.wait(timeout=10)
                if mode == "admin":
                    data = LessonAdminTests.data(self)
                    data.update(starts_at_1="18:00:00", ends_at_1="19:00:00")
                    response = client.post(reverse("admin:education_lesson_add"), data)
                    if response.status_code == 302:
                        return "created"
                    self.assertContains(response, "Пересечение с занятием")
                    return "conflict"
                try:
                    generate_lessons(self.day, 1, apply=True, schedule_id=extra.pk)
                    return "created"
                except ValidationError:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["admin", "generator"]))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(Lesson.objects.count(), 1)
