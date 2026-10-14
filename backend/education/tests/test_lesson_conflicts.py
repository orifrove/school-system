from datetime import timedelta
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from education.lesson_generation import generate_lessons
from education.models import Lesson
from education.tests import test_lesson_generation as fixtures
from users.models import User


class LessonConflictAuditTests(TestCase):
    def setUp(self):
        fixtures.LessonGenerationTests.setUp(self)
        generate_lessons(self.day, 1, apply=True)
        self.lesson = Lesson.objects.get()

    def duplicate(self, **changes):
        values = dict(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.lesson.starts_at + timedelta(minutes=30),
            ends_at=self.lesson.ends_at + timedelta(minutes=30), room="A")
        values.update(changes)
        return Lesson.objects.create(**values)

    def audit(self, **kwargs):
        out = StringIO()
        call_command("check_lesson_conflicts", start=self.day.isoformat(), days=1, stdout=out, **kwargs)
        return out.getvalue()

    def test_pair_counted_once_for_both_resources_and_no_writes(self):
        self.duplicate()
        before = list(Lesson.objects.order_by("pk").values())
        output = self.audit()
        self.assertIn("teacher, room", output)
        self.assertIn("conflict pairs: 1", output)
        self.assertEqual(before, list(Lesson.objects.order_by("pk").values()))

    def test_room_conflict_with_different_teachers(self):
        self.duplicate(teacher=User.objects.create_user(full_name="Other"))
        self.assertIn(": room;", self.audit())

    def test_teacher_conflict_with_different_rooms(self):
        self.duplicate(room="B")
        self.assertIn(": teacher;", self.audit())

    def test_adjacent_and_cancelled_lessons_do_not_conflict(self):
        self.duplicate(starts_at=self.lesson.ends_at, ends_at=self.lesson.ends_at + timedelta(hours=1))
        self.duplicate(status=Lesson.STATUS_CANCELLED)
        self.assertIn("conflict pairs: 0", self.audit())

    def test_blank_rooms_do_not_conflict(self):
        Lesson.objects.update(room="")
        self.duplicate(teacher=User.objects.create_user(full_name="Other"), room="")
        self.assertIn("conflict pairs: 0", self.audit())

    def test_limit_preserves_total_and_optional_failure(self):
        self.duplicate()
        self.duplicate(starts_at=self.lesson.starts_at + timedelta(minutes=45))
        output = self.audit(limit=1)
        self.assertIn("conflict pairs: 3; shown: 1", output)
        with self.assertRaises(CommandError):
            self.audit(fail_on_conflict=True)

    def test_cross_midnight_lesson_is_included_and_clipped(self):
        boundary = timezone.localtime(self.lesson.starts_at).replace(hour=0, minute=0)
        Lesson.objects.update(starts_at=boundary-timedelta(hours=1), ends_at=boundary+timedelta(hours=1))
        self.duplicate(starts_at=boundary, ends_at=boundary+timedelta(hours=2), status=Lesson.STATUS_HELD)
        self.assertIn("conflict pairs: 1", self.audit())
        self.assertIn("T00:00:00+05:00", self.audit())

    def test_outside_window_is_excluded(self):
        self.duplicate(starts_at=self.lesson.starts_at+timedelta(days=1), ends_at=self.lesson.ends_at+timedelta(days=1))
        self.assertIn("Checked lessons: 1; conflict pairs: 0", self.audit(fail_on_conflict=True))

    def test_invalid_parameters(self):
        for options in ({"start":"bad"}, {"start":"9999-12-31"}, {"days":0}, {"days":91}, {"limit":0}, {"limit":201}):
            with self.assertRaises(CommandError):
                call_command("check_lesson_conflicts", stdout=StringIO(), **options)
