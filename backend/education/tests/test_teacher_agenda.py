from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from education import teacher_services as services
from education.models import Attendance, Enrollment, Grade, Lesson, Schedule, Student
from education.tests.test_teacher_services import TeacherServicesTests


class TeacherAgendaTests(TestCase):
    def setUp(self):
        TeacherServicesTests.setUp(self)
        self.now = datetime(2026, 10, 3, 19, tzinfo=dt_timezone.utc)  # Oct 4, 00:00 Tashkent
        self.individual = Enrollment.objects.create(student=self.student, subject=self.subject,
            teacher=self.teacher, start_date="2026-10-04")
        self.ind_schedule = Schedule.objects.create(enrollment=self.individual, weekday=6,
            start_time="02:00", end_time="03:00", valid_from="2026-10-04")
        self.ind_lesson = Lesson.objects.create(schedule=self.ind_schedule, teacher=self.teacher,
            subject=self.subject, starts_at=self.now + timedelta(hours=2), ends_at=self.now + timedelta(hours=3))

    def agenda(self, period="today", page=0):
        with patch("education.teacher_services.timezone.now", return_value=self.now):
            return services.teacher_agenda(self.teacher.pk, period, page)

    def test_agenda_includes_group_and_individual_in_time_order(self):
        rows, more = self.agenda()
        self.assertEqual([l.pk for l in rows], [self.lesson.pk, self.ind_lesson.pk])
        self.assertFalse(more)

    def test_local_midnight_and_week_boundaries(self):
        tomorrow = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(days=1), ends_at=self.now + timedelta(days=1, hours=1))
        boundary = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(days=7), ends_at=self.now + timedelta(days=7, hours=1))
        self.assertEqual([l.pk for l in self.agenda("tomorrow")[0]], [tomorrow.pk])
        week = [l.pk for l in self.agenda("week")[0]]
        self.assertIn(tomorrow.pk, week)
        self.assertNotIn(boundary.pk, week)
        self.assertNotIn(tomorrow.pk, [l.pk for l in self.agenda()[0]])

    def test_cancelled_and_other_teacher_lessons_hidden(self):
        self.lesson.status = "cancelled"
        self.lesson.save()
        self.ind_lesson.teacher = self.other
        self.ind_lesson.save()
        self.assertEqual(self.agenda()[0], [])

    def test_reassigned_individual_enrollment_blocks_old_teacher(self):
        self.individual.teacher = self.other
        self.individual.save()
        self.assertNotIn(self.ind_lesson.pk, [l.pk for l in self.agenda()[0]])
        with self.assertRaises(PermissionDenied):
            services.record_teacher_attendance(self.teacher.pk, self.ind_lesson.pk, self.student.pk, "present")
        # Snapshot still names original teacher, so a new teacher cannot claim the old lesson either.
        with self.assertRaises(PermissionDenied):
            services.record_teacher_grade(self.other.pk, self.ind_lesson.pk, self.student.pk, "5", 0)

    def test_individual_roster_does_not_include_other_individual_students(self):
        stranger = Student.objects.create(full_name="Other individual")
        Enrollment.objects.create(student=stranger, teacher=self.teacher, subject=self.subject, start_date="2026-10-04")
        _, students, _, _ = services.lesson_roster(self.teacher.pk, self.ind_lesson.pk)
        self.assertEqual([s.pk for s in students], [self.student.pk])
        with self.assertRaises(PermissionDenied):
            services.record_teacher_attendance(self.teacher.pk, self.ind_lesson.pk, stranger.pk, "present")

    def test_individual_grade_uses_exact_enrollment_even_with_multiple_programs(self):
        Enrollment.objects.create(student=self.student, teacher=self.teacher, subject=self.subject, start_date="2026-10-04")
        grade = services.record_teacher_grade(self.teacher.pk, self.ind_lesson.pk, self.student.pk, "9/10", 0)
        self.assertEqual(grade.enrollment_id, self.individual.pk)
        services.record_teacher_attendance(self.teacher.pk, self.ind_lesson.pk, self.student.pk, "present")
        _, progress = services.lesson_progress(self.teacher.pk, self.ind_lesson.pk)
        self.assertEqual((progress["total"], progress["marked"], progress["graded"]), (1, 1, 1))

    def test_individual_date_range_and_status(self):
        self.individual.end_date = "2026-10-03"
        self.individual.save()
        self.assertNotIn(self.ind_lesson.pk, [l.pk for l in self.agenda()[0]])
        with self.assertRaises(PermissionDenied):
            services.record_teacher_grade(self.teacher.pk, self.ind_lesson.pk, self.student.pk, "5", 0)
        self.individual.end_date = None
        self.individual.status = "paused"
        self.individual.save()
        with self.assertRaises(PermissionDenied):
            services.lesson_roster(self.teacher.pk, self.ind_lesson.pk)

    def test_individual_inactive_student_cannot_be_marked(self):
        self.student.is_active = False
        self.student.save()
        self.assertNotIn(self.ind_lesson.pk, [l.pk for l in self.agenda()[0]])
        with self.assertRaises(PermissionDenied):
            services.record_teacher_attendance(self.teacher.pk, self.ind_lesson.pk, self.student.pk, "present")

    def test_agenda_bad_period_and_pagination(self):
        with self.assertRaises(ValidationError):
            self.agenda("forever")
        for number in range(10):
            Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
                starts_at=self.now + timedelta(hours=4, minutes=number), ends_at=self.now + timedelta(hours=5, minutes=number))
        first, more = self.agenda()
        second, more2 = self.agenda(page=1)
        self.assertEqual((len(first), more, len(second), more2), (8, True, 4, False))
        self.assertFalse({l.pk for l in first} & {l.pk for l in second})

    def test_individual_bot_flow_and_back_button(self):
        from bot.handlers.teacher import render_screen
        render = async_to_sync(render_screen)
        with patch("education.teacher_services.timezone.now", return_value=self.now):
            _, agenda = render(self.teacher.pk, "tg:agenda:today:0")
        button = next(b for row in agenda.inline_keyboard for b in row if b.callback_data == f"tg:roster:{self.ind_lesson.pk}:0")
        _, roster = render(self.teacher.pk, button.callback_data)
        self.assertEqual(roster.inline_keyboard[-1][0].callback_data, "tg:agenda:week:0")
        _, student = render(self.teacher.pk, roster.inline_keyboard[0][0].callback_data)
        render(self.teacher.pk, student.inline_keyboard[0][0].callback_data)
        grade_button = next(b for row in student.inline_keyboard for b in row if b.callback_data.startswith("tg:grade:"))
        _, grades = render(self.teacher.pk, grade_button.callback_data)
        render(self.teacher.pk, grades.inline_keyboard[0][-1].callback_data)
        self.assertEqual(Attendance.objects.get().lesson_id, self.ind_lesson.pk)
        self.assertEqual(Grade.objects.get().enrollment_id, self.individual.pk)
