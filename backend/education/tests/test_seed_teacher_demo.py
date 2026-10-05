from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from education.models import Attendance, Enrollment, Group, Lesson, Schedule, Student, Subject
from education.teacher_services import lesson_roster, record_teacher_attendance
from users.models import Role, User, UserRole


@override_settings(DEBUG=True)
class SeedTeacherDemoTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(full_name="Teacher")
        self.role = Role.objects.create(code=Role.TEACHER)
        UserRole.objects.create(user=self.teacher, role=self.role)

    def seed(self, teacher=None):
        call_command("seed_teacher_demo", teacher_id=(teacher or self.teacher).pk, stdout=StringIO())

    def test_repeat_run_is_idempotent_and_preserves_attendance_and_real_students(self):
        original = Student.objects.create(full_name="Existing student")
        self.seed()
        lesson = Lesson.objects.get()
        _, students, _, _ = lesson_roster(self.teacher.pk, lesson.pk)
        self.assertEqual(len(students), 2)
        self.assertNotIn(original, students)
        record_teacher_attendance(self.teacher.pk, lesson.pk, students[0].pk, "present")
        self.seed()
        self.assertEqual(Group.objects.count(), 1)
        self.assertEqual(Subject.objects.count(), 1)
        self.assertEqual(Student.objects.count(), 3)
        self.assertEqual(Enrollment.objects.count(), 2)
        self.assertEqual(Schedule.objects.count(), 1)
        self.assertEqual(Lesson.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().status, "present")

    @override_settings(DEBUG=False)
    def test_production_is_rejected(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Group.objects.exists())

    def test_role_required(self):
        UserRole.objects.all().delete()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Subject.objects.exists())

    def test_manual_teacher_change_is_preserved(self):
        self.seed()
        other = User.objects.create_user(full_name="Other")
        Group.objects.update(teacher=other)
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Group.objects.get().teacher, other)

    def test_two_teachers_get_separate_demo_groups_and_students(self):
        other = User.objects.create_user(full_name="Other")
        UserRole.objects.create(user=other, role=self.role)
        self.seed()
        self.seed(other)
        self.assertEqual(Group.objects.count(), 2)
        self.assertEqual(Student.objects.count(), 4)
        self.assertEqual(Lesson.objects.count(), 2)

    def test_partial_failure_rolls_back_all_demo_rows(self):
        with patch("education.management.commands.seed_teacher_demo.create_enrollment", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.seed()
        for model in [Subject, Group, Student, Enrollment, Schedule, Lesson]:
            self.assertEqual(model.objects.count(), 0)

    def test_individual_demo_is_repeatable_and_visible_in_agenda(self):
        from education.teacher_services import teacher_agenda
        for _ in range(2):
            call_command("seed_teacher_demo", teacher_id=self.teacher.pk, individual=True, stdout=StringIO())
        self.assertEqual(Enrollment.objects.filter(group__isnull=True).count(), 1)
        self.assertEqual(Student.objects.count(), 3)
        self.assertEqual(Lesson.objects.count(), 2)
        lessons, _ = teacher_agenda(self.teacher.pk)
        self.assertEqual(len(lessons), 2)
        individual = next(lesson for lesson in lessons if lesson.schedule.enrollment_id)
        _, students, _, _ = lesson_roster(self.teacher.pk, individual.pk)
        self.assertEqual(len(students), 1)
