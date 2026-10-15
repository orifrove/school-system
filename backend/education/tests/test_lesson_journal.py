from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from education.tests import test_lesson_generation as fixtures
from education.models import Lesson, Enrollment, Schedule, Student
from users.models import User


class LessonJournalTests(TestCase):
    def setUp(self):
        fixtures.LessonGenerationTests.setUp(self)
        self.admin_user = User.objects.create_superuser(username="admin", full_name="Admin", password="pass")
        self.client.force_login(self.admin_user)
        self.midnight = timezone.make_aware(datetime.combine(self.day, time.min), timezone.get_default_timezone())
        self.now = self.midnight + timedelta(minutes=30)
        self.url = reverse("admin:education_lesson_changelist")

    def lesson(self, offset, **changes):
        data = dict(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.midnight+offset, ends_at=self.midnight+offset+timedelta(minutes=15), room="Room Z")
        data.update(changes)
        return Lesson.objects.create(**data)

    def rows(self, **params):
        with patch("education.admin_filters.timezone.now", return_value=self.now):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return {row.pk for row in response.context["cl"].queryset}

    def test_today_uses_tashkent_date_and_excludes_next_midnight(self):
        self.lesson(timedelta(minutes=-1))
        first = self.lesson(timedelta())
        last = self.lesson(timedelta(hours=23, minutes=59))
        self.lesson(timedelta(days=1))
        self.assertEqual(self.rows(lesson_period="today"), {first.pk, last.pk})

    def test_tomorrow_boundaries(self):
        self.lesson(timedelta(hours=23))
        first = self.lesson(timedelta(days=1))
        last = self.lesson(timedelta(days=2, minutes=-1))
        self.lesson(timedelta(days=2))
        self.assertEqual(self.rows(lesson_period="tomorrow"), {first.pk, last.pk})

    def test_seven_days_include_today(self):
        first = self.lesson(timedelta())
        last = self.lesson(timedelta(days=7, minutes=-1))
        self.lesson(timedelta(days=7))
        self.assertEqual(self.rows(lesson_period="week"), {first.pk, last.pk})

    def test_overdue_means_ended_and_still_planned(self):
        ended = self.lesson(timedelta(minutes=15))
        ongoing = self.lesson(timedelta(minutes=20))
        self.lesson(timedelta(minutes=-30), status="held")
        self.lesson(timedelta(minutes=-60), status="cancelled")
        self.assertEqual(self.rows(lesson_period="overdue"), {ended.pk})
        self.assertNotIn(ongoing.pk, self.rows(lesson_period="overdue"))

    def test_period_and_status_filters_combine(self):
        self.lesson(timedelta())
        held = self.lesson(timedelta(hours=1), status="held")
        self.assertEqual(self.rows(lesson_period="today", status__exact="held"), {held.pk})

    def test_search_group_teacher_and_room(self):
        lesson = self.lesson(timedelta())
        for query in (self.group.name, self.teacher.full_name, "Room Z"):
            self.assertEqual(self.rows(q=query), {lesson.pk})
        self.assertEqual(self.rows(q="no matching text"), set())

    def test_individual_student_search_and_label(self):
        student = Student.objects.create(full_name="Individual learner")
        enrollment = Enrollment.objects.create(student=student, teacher=self.teacher, subject=self.subject, start_date=self.day)
        schedule = Schedule.objects.create(enrollment=enrollment, weekday=0, start_time="18:00", end_time="19:00", valid_from=self.day)
        lesson = self.lesson(timedelta(), schedule=schedule)
        self.assertEqual(self.rows(q=student.full_name), {lesson.pk})
        self.assertEqual(admin.site._registry[Lesson].learning_source(lesson), "Индивидуально: Individual learner")

    def test_unknown_period_preserves_list_and_browsing_is_read_only(self):
        lesson = self.lesson(timedelta())
        before = list(Lesson.objects.values())
        self.assertEqual(self.rows(lesson_period="unknown"), {lesson.pk})
        self.assertEqual(before, list(Lesson.objects.values()))

    def test_non_staff_cannot_view_journal(self):
        self.client.force_login(self.teacher)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_list_source_rendering_has_no_per_row_queries(self):
        self.lesson(timedelta())
        self.lesson(timedelta(hours=1))
        request = RequestFactory().get(self.url)
        request.user = self.admin_user
        model_admin = admin.site._registry[Lesson]
        changelist = model_admin.get_changelist_instance(request)
        lessons = list(changelist.queryset)
        with self.assertNumQueries(0):
            for lesson in lessons:
                self.assertEqual(model_admin.learning_source(lesson), self.group.name)
                str(lesson.teacher)
                str(lesson.subject)

    def test_daily_list_is_chronological(self):
        late = self.lesson(timedelta(hours=20))
        early = self.lesson(timedelta(hours=9))
        with patch("education.admin_filters.timezone.now", return_value=self.now):
            response = self.client.get(self.url, {"lesson_period":"today"})
        self.assertEqual(list(response.context["cl"].queryset.values_list("pk", flat=True)), [early.pk, late.pk])
