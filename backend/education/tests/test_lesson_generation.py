from datetime import date, time, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase, TransactionTestCase
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

    def extra_schedule(self, *, other_teacher=False, room="A", start=time(18, 30), end=time(19, 30)):
        group = self.group
        if other_teacher:
            teacher = User.objects.create_user(full_name="Other teacher")
            UserRole.objects.create(user=teacher, role=Role.objects.get(code=Role.TEACHER))
            group = Group.objects.create(name="Other group", subject=self.subject, teacher=teacher)
        return Schedule.objects.create(group=group, weekday=0, start_time=start,
            end_time=end, valid_from=self.day, room=room)

    def test_teacher_overlap_in_batch_blocks_every_write(self):
        self.extra_schedule(room="B")
        report = generate_lessons(self.day, 1)
        self.assertEqual((report["would_create"], report["conflicts"]), (2, 1))
        self.assertIn("teacher overlap", report["conflict_details"][0])
        with self.assertRaises(ValidationError):
            generate_lessons(self.day, 1, apply=True)
        self.assertFalse(Lesson.objects.exists())

    def test_shared_room_with_different_teachers_blocks_apply(self):
        self.extra_schedule(other_teacher=True)
        self.assertIn("room overlap", generate_lessons(self.day, 1)["conflict_details"][0])
        with self.assertRaises(ValidationError):
            generate_lessons(self.day, 1, apply=True)
        self.assertFalse(Lesson.objects.exists())

    def test_adjacent_lessons_are_allowed(self):
        self.extra_schedule(start=time(19), end=time(20))
        self.assertEqual(generate_lessons(self.day, 1, apply=True)["created"], 2)

    def test_different_resources_can_overlap(self):
        self.extra_schedule(other_teacher=True, room="B")
        self.assertEqual(generate_lessons(self.day, 1, apply=True)["created"], 2)

    def test_blank_room_does_not_claim_a_resource(self):
        self.schedule.room = ""
        self.schedule.save()
        self.extra_schedule(other_teacher=True, room="")
        self.assertEqual(generate_lessons(self.day, 1, apply=True)["created"], 2)

    def test_existing_held_lesson_blocks_selected_schedule_without_changes(self):
        generate_lessons(self.day, 1, apply=True)
        Lesson.objects.update(status=Lesson.STATUS_HELD)
        before = list(Lesson.objects.values())
        extra = self.extra_schedule(other_teacher=True)
        report = generate_lessons(self.day, 1, schedule_id=extra.pk)
        self.assertIn("room overlap with lesson#", report["conflict_details"][0])
        with self.assertRaises(ValidationError):
            generate_lessons(self.day, 1, apply=True, schedule_id=extra.pk)
        self.assertEqual(before, list(Lesson.objects.values()))

    def test_cancelled_lesson_frees_resources(self):
        generate_lessons(self.day, 1, apply=True)
        Lesson.objects.update(status=Lesson.STATUS_CANCELLED)
        extra = self.extra_schedule()
        self.assertEqual(generate_lessons(self.day, 1, apply=True, schedule_id=extra.pk)["created"], 1)
        self.assertEqual(Lesson.objects.filter(status=Lesson.STATUS_CANCELLED).count(), 1)

    def test_date_overflow_is_validation_error(self):
        with self.assertRaises(ValidationError):
            generate_lessons(date.max, 2)

    def test_command_reports_conflict_and_refuses_apply(self):
        self.extra_schedule()
        output = StringIO()
        call_command("generate_lessons", start=self.day.isoformat(), days=1, stdout=output)
        self.assertIn("CONFLICT:", output.getvalue())
        self.assertIn("Apply is blocked", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("generate_lessons", start=self.day.isoformat(), days=1, apply=True, stdout=StringIO())
        self.assertFalse(Lesson.objects.exists())


class ConcurrentLessonGenerationTests(TransactionTestCase):
    def test_parallel_generators_cannot_double_book_room(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections

        LessonGenerationTests.setUp(self)
        extra = LessonGenerationTests.extra_schedule(self, other_teacher=True)
        barrier = Barrier(2)

        def run(schedule_id):
            try:
                barrier.wait(timeout=10)
                try:
                    generate_lessons(self.day, 1, apply=True, schedule_id=schedule_id)
                    return "created"
                except ValidationError:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [self.schedule.pk, extra.pk]))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(Lesson.objects.count(), 1)
