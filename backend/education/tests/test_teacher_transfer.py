from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from education.tests import test_lesson_generation as fixtures
from education.lesson_generation import generate_lessons
from education.models import Lesson, Group, Schedule
from education.services import change_group_teacher
from users.models import User, UserRole, Role


class TeacherTransferTests(TestCase):
    def setUp(self):
        fixtures.LessonGenerationTests.setUp(self)
        generate_lessons(self.day, 1, apply=True)
        self.lesson = Lesson.objects.get()
        self.target = User.objects.create_user(full_name="New teacher")
        UserRole.objects.create(user=self.target, role=Role.objects.get(code=Role.TEACHER))
        self.other_group = Group.objects.create(name="Other", teacher=self.target, subject=self.subject)
        self.other_schedule = Schedule.objects.create(group=self.other_group, weekday=0,
            start_time="18:30", end_time="19:30", valid_from=self.day)

    def other_lesson(self, **changes):
        data = dict(schedule=self.other_schedule, teacher=self.target, subject=self.subject,
            starts_at=self.lesson.starts_at+timedelta(minutes=30), ends_at=self.lesson.ends_at+timedelta(minutes=30))
        data.update(changes)
        return Lesson.objects.create(**data)

    def test_conflict_preserves_entire_group_and_lesson(self):
        self.other_lesson()
        with self.assertRaisesMessage(ValidationError, "Смена преподавателя создаст пересечение"):
            change_group_teacher(self.group, self.target)
        self.group.refresh_from_db(); self.lesson.refresh_from_db()
        self.assertEqual(self.group.teacher_id, self.teacher.pk)
        self.assertEqual(self.lesson.teacher_id, self.teacher.pk)

    def test_held_conflict_also_blocks(self):
        self.other_lesson(status="held")
        with self.assertRaises(ValidationError):
            change_group_teacher(self.group, self.target)

    def test_cancelled_conflict_is_ignored(self):
        self.other_lesson(status="cancelled")
        change_group_teacher(self.group, self.target)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.teacher_id, self.target.pk)

    def test_adjacent_lesson_is_allowed(self):
        self.other_lesson(starts_at=self.lesson.ends_at, ends_at=self.lesson.ends_at+timedelta(hours=1))
        change_group_teacher(self.group, self.target)
        self.group.refresh_from_db()
        self.assertEqual(self.group.teacher_id, self.target.pk)

    def test_overlapping_lessons_inside_group_are_rejected(self):
        self.other_lesson(schedule=self.schedule, teacher=self.teacher)
        with self.assertRaises(ValidationError):
            change_group_teacher(self.group, self.target)

    def test_history_keeps_original_teacher(self):
        held = self.other_lesson(schedule=self.schedule, teacher=self.teacher, status="held")
        cancelled = self.other_lesson(schedule=self.schedule, teacher=self.teacher, status="cancelled",
            starts_at=self.lesson.starts_at-timedelta(days=1))
        change_group_teacher(self.group, self.target)
        held.refresh_from_db(); cancelled.refresh_from_db()
        self.assertEqual((held.teacher_id, cancelled.teacher_id), (self.teacher.pk, self.teacher.pk))

    def test_same_teacher_is_noop_even_with_legacy_conflict(self):
        self.other_lesson(teacher=self.teacher)
        change_group_teacher(self.group, self.teacher)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.teacher_id, self.teacher.pk)

    def test_admin_reports_conflict_and_does_not_save_other_fields(self):
        self.other_lesson()
        admin = User.objects.create_superuser(username="admin", full_name="Admin", password="pass")
        self.client.force_login(admin)
        response = self.client.post(reverse("admin:education_group_change", args=[self.group.pk]), {
            "name":"Changed name", "subject":self.subject.pk, "teacher":self.target.pk,
            "capacity":20, "is_active":"on", "enrollments-TOTAL_FORMS":0, "enrollments-INITIAL_FORMS":0,
            "enrollments-MIN_NUM_FORMS":0, "enrollments-MAX_NUM_FORMS":1000})
        self.assertContains(response, "Смена преподавателя создаст пересечение")
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Group")
        self.assertEqual(self.group.teacher_id, self.teacher.pk)

    def test_admin_success_updates_group_and_planned_lesson(self):
        admin = User.objects.create_superuser(username="admin", full_name="Admin", password="pass")
        self.client.force_login(admin)
        response = self.client.post(reverse("admin:education_group_change", args=[self.group.pk]), {
            "name":"Changed name", "subject":self.subject.pk, "teacher":self.target.pk,
            "capacity":20, "is_active":"on", "enrollments-TOTAL_FORMS":0, "enrollments-INITIAL_FORMS":0,
            "enrollments-MIN_NUM_FORMS":0, "enrollments-MAX_NUM_FORMS":1000})
        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db(); self.lesson.refresh_from_db()
        self.assertEqual(self.group.name, "Changed name")
        self.assertEqual((self.group.teacher_id, self.lesson.teacher_id), (self.target.pk, self.target.pk))


class ConcurrentTeacherTransferTests(TransactionTestCase):
    def test_parallel_transfers_to_one_teacher_cannot_overlap(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        TeacherTransferTests.setUp(self)
        third = User.objects.create_user(full_name="Third")
        self.other_group.teacher = third; self.other_group.save()
        TeacherTransferTests.other_lesson(self, teacher=third)
        barrier = Barrier(2)

        def run(group_id):
            try:
                group = Group.objects.get(pk=group_id)
                barrier.wait(timeout=10)
                try:
                    change_group_teacher(group, self.target)
                    return "changed"
                except ValidationError:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [self.group.pk, self.other_group.pk]))
        self.assertCountEqual(results, ["changed", "conflict"])
        self.assertEqual(Lesson.objects.filter(teacher=self.target).count(), 1)
