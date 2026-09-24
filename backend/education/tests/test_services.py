from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils.dateparse import parse_datetime

from education import services
from education.models import Attendance, Enrollment, Grade, Group, Lesson, Schedule, Student, Subject
from users.models import User


class UpdateGroupTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Математика")
        self.other_subject = Subject.objects.create(name="Английский")
        self.teacher = User.objects.create_user(full_name="Учитель А")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="9А")

    def test_can_change_subject_without_history(self):
        services.update_group(self.group, subject=self.other_subject)
        self.group.refresh_from_db()
        self.assertEqual(self.group.subject, self.other_subject)

    def test_cannot_change_subject_with_enrollment_history(self):
        student = Student.objects.create(full_name="Ученик")
        Enrollment.objects.create(student=student, group=self.group, start_date="2026-09-01")

        with self.assertRaises(ValidationError):
            services.update_group(self.group, subject=self.other_subject)

    def test_can_change_other_fields_freely(self):
        services.update_group(self.group, name="9А (новое название)")
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "9А (новое название)")


class ChangeGroupTeacherTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Физика")
        self.teacher_a = User.objects.create_user(full_name="Учитель A")
        self.teacher_b = User.objects.create_user(full_name="Учитель B")
        self.group = Group.objects.create(subject=subject, teacher=self.teacher_a, name="10А")
        self.schedule = Schedule.objects.create(
            group=self.group, weekday=1, start_time="10:00", end_time="11:00", valid_from="2026-09-01"
        )

    def test_planned_lesson_updated_held_lesson_not(self):
        planned = Lesson.objects.create(
            schedule=self.schedule, teacher=self.teacher_a, subject=self.group.subject,
            starts_at=parse_datetime("2026-09-30T10:00:00Z"),
            ends_at=parse_datetime("2026-09-30T11:00:00Z"),
            status=Lesson.STATUS_PLANNED,
        )
        held = Lesson.objects.create(
            schedule=self.schedule, teacher=self.teacher_a, subject=self.group.subject,
            starts_at=parse_datetime("2026-09-02T10:00:00Z"),
            ends_at=parse_datetime("2026-09-02T11:00:00Z"),
            status=Lesson.STATUS_HELD,
        )

        services.change_group_teacher(self.group, self.teacher_b)

        planned.refresh_from_db()
        held.refresh_from_db()
        self.assertEqual(planned.teacher, self.teacher_b)  # обновлён
        self.assertEqual(held.teacher, self.teacher_a)      # НЕ обновлён


class MarkAttendanceTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Химия")
        self.teacher = User.objects.create_user(full_name="Учитель Химии")
        self.group = Group.objects.create(subject=subject, teacher=self.teacher, name="8А")
        self.schedule = Schedule.objects.create(
            group=self.group, weekday=0, start_time="09:00", end_time="09:45", valid_from="2026-09-01"
        )
        self.lesson = Lesson.objects.create(
            schedule=self.schedule, teacher=self.teacher, subject=subject,
            starts_at=parse_datetime("2026-09-07T09:00:00Z"),
            ends_at=parse_datetime("2026-09-07T09:45:00Z"),
        )
        self.enrolled_student = Student.objects.create(full_name="Зачисленный")
        Enrollment.objects.create(student=self.enrolled_student, group=self.group, start_date="2026-09-01")
        self.stranger_student = Student.objects.create(full_name="Посторонний")

    def test_mark_attendance_for_enrolled_student(self):
        attendance = services.mark_attendance(self.lesson, self.enrolled_student, Attendance.STATUS_PRESENT)
        self.assertEqual(attendance.status, Attendance.STATUS_PRESENT)

    def test_cannot_mark_attendance_for_stranger(self):
        with self.assertRaises(ValidationError):
            services.mark_attendance(self.lesson, self.stranger_student, Attendance.STATUS_PRESENT)

    def test_marking_twice_updates_not_duplicates(self):
        services.mark_attendance(self.lesson, self.enrolled_student, Attendance.STATUS_ABSENT)
        services.mark_attendance(self.lesson, self.enrolled_student, Attendance.STATUS_PRESENT)

        records = Attendance.objects.filter(lesson=self.lesson, student=self.enrolled_student)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().status, Attendance.STATUS_PRESENT)


class CreateEnrollmentTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Биология")
        teacher = User.objects.create_user(full_name="Учитель Биологии")
        self.group = Group.objects.create(subject=subject, teacher=teacher, name="6Б")
        self.student = Student.objects.create(full_name="Ученик Овервлап")

    def test_create_enrollment_no_overlap(self):
        services.create_enrollment(self.student, start_date="2026-09-01", end_date="2026-11-01", group=self.group)
        enrollment = services.create_enrollment(
            self.student, start_date="2026-11-02", group=self.group
        )
        self.assertIsNotNone(enrollment.id)

    def test_cannot_create_overlapping_enrollment(self):
        services.create_enrollment(self.student, start_date="2026-09-01", end_date="2026-11-01", group=self.group)
        with self.assertRaises(ValidationError):
            services.create_enrollment(self.student, start_date="2026-10-15", group=self.group)


class AddGradeTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Информатика")
        self.teacher = User.objects.create_user(full_name="Учитель Информатики")
        self.group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="9В")
        self.other_group = Group.objects.create(subject=self.subject, teacher=self.teacher, name="9Г")
        self.student = Student.objects.create(full_name="Ученик Грейдов")
        self.enrollment = Enrollment.objects.create(student=self.student, group=self.group, start_date="2026-09-01")

        schedule = Schedule.objects.create(
            group=self.group, weekday=2, start_time="11:00", end_time="12:00", valid_from="2026-09-01"
        )
        self.lesson_same_group = Lesson.objects.create(
            schedule=schedule, teacher=self.teacher, subject=self.subject,
            starts_at=parse_datetime("2026-09-09T11:00:00Z"), ends_at=parse_datetime("2026-09-09T12:00:00Z"),
        )

        other_schedule = Schedule.objects.create(
            group=self.other_group, weekday=3, start_time="13:00", end_time="14:00", valid_from="2026-09-01"
        )
        self.lesson_other_group = Lesson.objects.create(
            schedule=other_schedule, teacher=self.teacher, subject=self.subject,
            starts_at=parse_datetime("2026-09-10T13:00:00Z"), ends_at=parse_datetime("2026-09-10T14:00:00Z"),
        )

    def test_add_grade_without_lesson(self):
        grade = services.add_grade(
            self.enrollment, self.teacher, "9", given_at=parse_datetime("2026-09-30T12:00:00Z")
        )
        self.assertIsNone(grade.lesson)

    def test_add_grade_with_matching_lesson(self):
        grade = services.add_grade(
            self.enrollment, self.teacher, "10", lesson=self.lesson_same_group,
            given_at=parse_datetime("2026-09-09T12:00:00Z"),
        )
        self.assertEqual(grade.lesson, self.lesson_same_group)

    def test_cannot_add_grade_with_lesson_from_other_group(self):
        with self.assertRaises(ValidationError):
            services.add_grade(
                self.enrollment, self.teacher, "5", lesson=self.lesson_other_group,
                given_at=parse_datetime("2026-09-10T14:00:00Z"),
            )