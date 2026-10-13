from datetime import date, time, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from education.lesson_generation import generate_lessons
from education.models import Enrollment, Group, Lesson, Schedule, Student, Subject
from users.models import Role, User, UserRole


class LessonGenerationTests(TestCase):
    def setUp(self):
        self.day = date(2026, 10, 12)
        self.teacher = User.objects.create_user(full_name="Teacher")
        UserRole.objects.create(user=self.teacher, role=Role.objects.create(code=Role.TEACHER))
        self.subject = Subject.objects.create(name="Subject")
        self.group = Group.objects.create(name="Group", subject=self.subject, teacher=self.teacher)
        self.schedule = Schedule.objects.create(group=self.group, weekday=0, start_time=time(18),
            end_time=time(19), valid_from=self.day, room="A")

    def test_preview_has_no_writes(self):
        report = generate_lessons(self.day, 14)
        self.assertEqual(report["would_create"], 2)
        self.assertEqual(Lesson.objects.count(), 0)

    def test_apply_is_repeatable_and_snapshots_local_time_and_room(self):
        report = generate_lessons(self.day, 14, apply=True)
        self.assertEqual(report["created"], 2)
        lesson = Lesson.objects.order_by("starts_at").first()
        local = timezone.localtime(lesson.starts_at)
        self.assertEqual((local.date(), local.hour), (self.day, 18))
        self.assertEqual(lesson.room, "A")
        self.assertEqual(lesson.teacher_id, self.teacher.pk)
        self.assertEqual(lesson.ends_at - lesson.starts_at, timedelta(hours=1))
        again = generate_lessons(self.day, 14, apply=True)
        self.assertEqual((again["created"], again["existing"]), (0, 2))

    def test_existing_cancelled_and_held_records_are_not_replaced(self):
        generate_lessons(self.day, 14, apply=True)
        lessons = list(Lesson.objects.order_by("starts_at"))
        for lesson, status in zip(lessons, ["held", "cancelled"]):
            lesson.status = status
            lesson.room = "Historical"
            lesson.save()
        self.schedule.room = "New"
        self.schedule.end_time = time(20)
        self.schedule.save()
        before = list(Lesson.objects.order_by("pk").values())
        generate_lessons(self.day, 14, apply=True)
        self.assertEqual(before, list(Lesson.objects.order_by("pk").values()))

    def test_schedule_validity_dates_are_inclusive(self):
        self.schedule.valid_from = self.day + timedelta(days=7)
        self.schedule.valid_until = self.day + timedelta(days=7)
        self.schedule.save()
        self.assertEqual(generate_lessons(self.day, 21, apply=True)["created"], 1)

    def test_individual_dates_and_paused_enrollment(self):
        student = Student.objects.create(full_name="Student")
        enrollment = Enrollment.objects.create(student=student, subject=self.subject, teacher=self.teacher,
            start_date=self.day + timedelta(days=7), end_date=self.day + timedelta(days=7))
        schedule = Schedule.objects.create(enrollment=enrollment, weekday=0, start_time=time(19), end_time=time(20), valid_from=self.day)
        report = generate_lessons(self.day, 21, apply=True, schedule_id=schedule.pk)
        self.assertEqual((report["created"], report["skipped"]), (1, 2))
        enrollment.status = "paused"
        enrollment.save()
        self.assertEqual(generate_lessons(self.day, 21, schedule_id=schedule.pk)["skipped"], 3)

    def test_inactive_source_and_teacher_without_role_are_skipped(self):
        self.group.is_active = False
        self.group.save()
        self.assertEqual(generate_lessons(self.day, 1)["skipped"], 1)
        self.group.is_active = True
        self.group.save()
        UserRole.objects.filter(user=self.teacher).delete()
        self.assertEqual(generate_lessons(self.day, 1)["skipped"], 1)

    def test_invalid_schedule_rolls_back_entire_apply(self):
        Schedule.objects.create(group=self.group, weekday=0, start_time=time(20), end_time=time(19), valid_from=self.day)
        with self.assertRaises(ValidationError):
            generate_lessons(self.day, 1, apply=True)
        self.assertFalse(Lesson.objects.exists())

    def test_invalid_range_and_missing_schedule_are_rejected(self):
        for days in [0, 91, True]:
            with self.assertRaises(ValidationError):
                generate_lessons(self.day, days)
        with self.assertRaises(ValidationError):
            generate_lessons(self.day, schedule_id=999999)

    def test_command_defaults_to_preview_and_validates_date(self):
        output = StringIO()
        call_command("generate_lessons", start="2026-10-12", days=1, stdout=output)
        self.assertIn("PREVIEW ONLY", output.getvalue())
        self.assertFalse(Lesson.objects.exists())
        with self.assertRaises(CommandError):
            call_command("generate_lessons", start="2026-02-30", stdout=StringIO())

    def test_inactive_schedule_is_ignored(self):
        self.schedule.is_active = False
        self.schedule.save()
        self.assertEqual(generate_lessons(self.day, 14, apply=True)["created"], 0)
