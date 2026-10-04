from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from zoneinfo import ZoneInfo
from asgiref.sync import async_to_sync

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase

from education import services, teacher_services
from education.models import Attendance, Enrollment, Grade, Group, Lesson, Schedule, Student, Subject
from users.models import Role, User, UserRole


class TeacherServicesTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(full_name="Teacher")
        self.other = User.objects.create_user(full_name="Other")
        self.role = Role.objects.create(code=Role.TEACHER)
        UserRole.objects.create(user=self.teacher, role=self.role)
        UserRole.objects.create(user=self.other, role=self.role)
        self.subject = Subject.objects.create(name="Math")
        self.group = Group.objects.create(name="A", subject=self.subject, teacher=self.teacher)
        self.foreign = Group.objects.create(name="B", subject=self.subject, teacher=self.other)
        self.schedule = Schedule.objects.create(group=self.group, weekday=0,
            start_time="00:30", end_time="01:30", valid_from="2026-10-04")
        # UTC date is October 3; enrollment starts on October 4 in Tashkent.
        starts = datetime(2026, 10, 4, 0, 30, tzinfo=ZoneInfo("Asia/Tashkent"))
        self.lesson = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher,
            subject=self.subject, starts_at=starts, ends_at=starts + timedelta(hours=1))
        self.student = Student.objects.create(full_name="Student <one>")
        self.enrollment = Enrollment.objects.create(student=self.student, group=self.group, start_date="2026-10-04")

    def test_groups_hide_foreign_and_inactive(self):
        Group.objects.create(name="Inactive", subject=self.subject, teacher=self.teacher, is_active=False)
        rows, more = teacher_services.teacher_groups(self.teacher.pk)
        self.assertEqual([x.pk for x in rows], [self.group.pk])
        self.assertFalse(more)

    def test_role_and_active_account_required(self):
        UserRole.objects.filter(user=self.teacher).delete()
        with self.assertRaises(PermissionDenied):
            teacher_services.teacher_groups(self.teacher.pk)
        UserRole.objects.create(user=self.teacher, role=self.role)
        self.teacher.is_active = False
        self.teacher.save()
        with self.assertRaises(PermissionDenied):
            teacher_services.teacher_groups(self.teacher.pk)

    def test_pagination_and_invalid_page(self):
        for n in range(10):
            Group.objects.create(name=f"Extra {n}", subject=self.subject, teacher=self.teacher)
        first, more = teacher_services.teacher_groups(self.teacher.pk)
        second, more2 = teacher_services.teacher_groups(self.teacher.pk, 1)
        self.assertEqual(len(first), 8)
        self.assertTrue(more)
        self.assertEqual(len(second), 3)
        self.assertFalse(more2)
        self.assertFalse({x.pk for x in first} & {x.pk for x in second})
        with self.assertRaises(ValidationError):
            teacher_services.teacher_groups(self.teacher.pk, -1)

    def test_foreign_group_and_lesson_denied(self):
        with self.assertRaises(PermissionDenied):
            teacher_services.group_lessons(self.teacher.pk, self.foreign.pk)
        with self.assertRaises(PermissionDenied):
            teacher_services.lesson_roster(self.other.pk, self.lesson.pk)
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_attendance(self.other.pk, self.lesson.pk, self.student.pk, "present")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_local_date_eligibility_and_repeat_update(self):
        _, students, _, _ = teacher_services.lesson_roster(self.teacher.pk, self.lesson.pk)
        self.assertEqual([x.pk for x in students], [self.student.pk])
        teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "absent")
        teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "present")
        attendance = Attendance.objects.get()
        self.assertEqual(attendance.status, "present")
        self.assertEqual(attendance.marked_by, self.teacher)
        self.assertIsNotNone(attendance.marked_at)

    def test_stranger_invalid_status_and_inactive_student_denied(self):
        stranger = Student.objects.create(full_name="Stranger")
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, stranger.pk, "present")
        with self.assertRaises(ValidationError):
            teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "invented")
        self.student.is_active = False
        self.student.save()
        with self.assertRaises(PermissionDenied):
            teacher_services.attendance_student(self.teacher.pk, self.lesson.pk, self.student.pk)
        self.assertFalse(Attendance.objects.exists())

    def test_cancelled_lesson_is_not_writable_or_listed(self):
        self.lesson.status = "cancelled"
        self.lesson.save()
        _, lessons, _ = teacher_services.group_lessons(self.teacher.pk, self.group.pk)
        self.assertEqual(lessons, [])
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "present")

    def test_stale_teacher_button_denied_after_reassignment(self):
        services.change_group_teacher(self.group, self.other)
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "present")
        teacher_services.record_teacher_attendance(self.other.pk, self.lesson.pk, self.student.pk, "present")
        self.assertEqual(Attendance.objects.get().marked_by, self.other)

    def test_enrollment_outside_lesson_date_is_hidden(self):
        self.enrollment.start_date = "2026-10-05"
        self.enrollment.save()
        _, students, _, _ = teacher_services.lesson_roster(self.teacher.pk, self.lesson.pk)
        self.assertEqual(students, [])
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_attendance(self.teacher.pk, self.lesson.pk, self.student.pk, "present")

    def test_missing_lesson_does_not_leak_database_error(self):
        with self.assertRaises(PermissionDenied):
            teacher_services.lesson_roster(self.teacher.pk, 9999999)

    def test_real_teacher_screen_flow_saves_attendance(self):
        from bot.handlers.teacher import render_screen
        render = async_to_sync(render_screen)
        _, groups = render(self.teacher.pk, "tg:groups:0")
        _, lessons = render(self.teacher.pk, groups.inline_keyboard[0][0].callback_data)
        _, roster = render(self.teacher.pk, lessons.inline_keyboard[0][0].callback_data)
        text, choices = render(self.teacher.pk, roster.inline_keyboard[0][0].callback_data)
        self.assertIn("&lt;one&gt;", text)
        text, back = render(self.teacher.pk, choices.inline_keyboard[0][0].callback_data)
        self.assertIn("сохранена", text)
        self.assertEqual(Attendance.objects.get().status, "present")
        _, roster = render(self.teacher.pk, back.inline_keyboard[0][0].callback_data)
        self.assertIn("Присутствует", roster.inline_keyboard[0][0].text)

    def test_forged_status_button_is_rejected_without_write(self):
        from bot.handlers.teacher import render_screen
        render = async_to_sync(render_screen)
        with self.assertRaises(PermissionDenied):
            render(self.other.pk, f"tg:set:{self.lesson.pk}:{self.student.pk}:present:0")
        for bad_data in ["tg:set:1:2:present:-1", "tg:groups:-1", "tg:groups:99999999999", "tg:set:1:2:present:0:extra"]:
            with self.assertRaises(ValueError):
                render(self.teacher.pk, bad_data)
        self.assertFalse(Attendance.objects.exists())

    def test_grade_uses_correct_enrollment_lesson_and_author(self):
        grade = teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, " 8/10 ", 0)
        self.assertEqual(grade.value, "8/10")
        self.assertEqual(grade.enrollment, self.enrollment)
        self.assertEqual(grade.lesson, self.lesson)
        self.assertEqual(grade.given_by_teacher, self.teacher)
        self.assertIsNotNone(grade.given_at)

    def test_stale_grade_button_cannot_duplicate_or_change_grade(self):
        grade = teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "5", 0)
        for value in ["5", "2"]:
            with self.assertRaises(ValidationError):
                teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, value, 0)
        self.assertEqual(Grade.objects.count(), 1)
        _, _, _, version = teacher_services.grade_context(self.teacher.pk, self.lesson.pk, self.student.pk)
        self.assertEqual(version, grade.pk)
        teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "A", version)
        self.assertEqual(Grade.objects.count(), 2)
        grade.refresh_from_db()
        self.assertEqual(grade.value, "5")

    def test_invalid_grade_values_do_not_write(self):
        for value in ["", "   ", "1" * 17, "A\nB", "A\x00B"]:
            with self.assertRaises(ValidationError):
                teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, value, 0)
        self.assertFalse(Grade.objects.exists())

    def test_grade_permission_is_rechecked(self):
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_grade(self.other.pk, self.lesson.pk, self.student.pk, "5", 0)
        self.enrollment.status = "ended"
        self.enrollment.save()
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "5", 0)
        self.assertFalse(Grade.objects.exists())

    def test_cancelled_lesson_and_revoked_role_reject_grade(self):
        self.lesson.status = "cancelled"
        self.lesson.save()
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "5", 0)
        self.lesson.status = "planned"
        self.lesson.save()
        UserRole.objects.filter(user=self.teacher).delete()
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "5", 0)

    def test_ambiguous_enrollment_does_not_assign_grade_arbitrarily(self):
        Enrollment.objects.create(student=self.student, group=self.group, start_date="2026-10-04")
        with self.assertRaises(PermissionDenied):
            teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "5", 0)
        self.assertFalse(Grade.objects.exists())

    def test_grade_buttons_save_and_show_assessment(self):
        from bot.handlers.teacher import render_screen
        render = async_to_sync(render_screen)
        _, card = render(self.teacher.pk, f"tg:student:{self.lesson.pk}:{self.student.pk}:0")
        grade_button = next(b for row in card.inline_keyboard for b in row if b.callback_data.startswith("tg:grade:"))
        _, choices = render(self.teacher.pk, grade_button.callback_data)
        self.assertEqual([b.text for b in choices.inline_keyboard[0]], ["2", "3", "4", "5"])
        save = choices.inline_keyboard[0][-1].callback_data
        text, back = render(self.teacher.pk, save)
        self.assertIn("5", text)
        self.assertEqual(Grade.objects.get().value, "5")
        with self.assertRaises(ValidationError):
            render(self.teacher.pk, save)
        text, _ = render(self.teacher.pk, back.inline_keyboard[0][0].callback_data)
        self.assertIn("Последние оценки: 5", text)

    def test_custom_grade_prompt_and_stale_prompt(self):
        from bot.handlers.teacher import render_screen
        render = async_to_sync(render_screen)
        _, choices = render(self.teacher.pk, f"tg:grade:{self.lesson.pk}:{self.student.pk}:0")
        custom = choices.inline_keyboard[1][0].callback_data
        text, _ = render(self.teacher.pk, custom)
        self.assertIn("8/10", text)
        self.assertFalse(Grade.objects.exists())
        teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, "A", 0)
        with self.assertRaises(ValidationError):
            render(self.teacher.pk, custom)


class ConcurrentGradeTests(TransactionTestCase):
    def setUp(self):
        TeacherServicesTests.setUp(self)

    def test_concurrent_clicks_create_only_one_assessment(self):
        barrier = Barrier(2)

        def save(value):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    teacher_services.record_teacher_grade(self.teacher.pk, self.lesson.pk, self.student.pk, value, 0)
                    return "saved"
                except ValidationError:
                    return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ["4", "5"]))
        self.assertCountEqual(results, ["saved", "stale"])
        self.assertEqual(Grade.objects.count(), 1)
