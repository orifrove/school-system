from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from education import parent_services as services
from education.models import Attendance, Enrollment, Grade, Group, Lesson, ParentStudent, Schedule, Student, Subject
from users.models import Role, User, UserRole


class ParentServicesTests(TestCase):
    def setUp(self):
        self.parent = User.objects.create_user(full_name="Parent")
        self.other = User.objects.create_user(full_name="Other Parent")
        self.teacher = User.objects.create_user(full_name="Teacher")
        self.role = Role.objects.create(code=Role.PARENT)
        for user in [self.parent, self.other]:
            UserRole.objects.create(user=user, role=self.role)
        self.child = Student.objects.create(full_name="Child <A&B>")
        self.foreign = Student.objects.create(full_name="Other Child")
        self.link = ParentStudent.objects.create(parent=self.parent, student=self.child)
        ParentStudent.objects.create(parent=self.other, student=self.foreign)
        self.subject = Subject.objects.create(name="Math <A&B>")
        self.group = Group.objects.create(name="Group", teacher=self.teacher, subject=self.subject)
        self.enrollment = Enrollment.objects.create(student=self.child, group=self.group, start_date="2050-01-02")
        self.schedule = Schedule.objects.create(group=self.group, weekday=6, start_time="02:00", end_time="03:00", valid_from="2050-01-02")
        self.now = datetime(2050, 1, 1, 20, tzinfo=dt_timezone.utc)
        self.lesson = Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(hours=1), ends_at=self.now + timedelta(hours=2), room="Room <1>")

    def upcoming(self):
        with patch("education.parent_services.timezone.now", return_value=self.now):
            return services.child_upcoming_lessons(self.parent.pk, self.child.pk)

    def grade(self, enrollment=None, lesson=True):
        return Grade.objects.create(enrollment=enrollment or self.enrollment, lesson=self.lesson if lesson else None,
            given_by_teacher=self.teacher, value="5", given_at=self.now)

    def test_children_only_show_current_linked_active_children(self):
        inactive = Student.objects.create(full_name="Inactive", is_active=False)
        ParentStudent.objects.create(parent=self.parent, student=inactive)
        children, more = services.parent_children(self.parent.pk)
        self.assertEqual([c.pk for c in children], [self.child.pk])
        self.assertFalse(more)

    def test_role_alone_does_not_grant_child_access(self):
        for operation in [services.child_profile, services.child_grades, services.child_attendance, services.child_upcoming_lessons]:
            with self.assertRaises(PermissionDenied):
                operation(self.other.pk, self.child.pk)

    def test_role_and_active_user_required_even_with_relationship(self):
        UserRole.objects.filter(user=self.parent).delete()
        with self.assertRaises(PermissionDenied):
            services.child_profile(self.parent.pk, self.child.pk)
        UserRole.objects.create(user=self.parent, role=self.role)
        self.parent.is_active = False
        self.parent.save()
        with self.assertRaises(PermissionDenied):
            services.parent_children(self.parent.pk)

    def test_revoked_link_and_inactive_child_reject_stale_buttons(self):
        from bot.handlers.parent import render_parent_screen
        render = async_to_sync(render_parent_screen)
        render(self.parent.pk, f"pg:child:{self.child.pk}")
        self.link.delete()
        for action in ["grades", "attendance", "upcoming"]:
            with self.assertRaises(PermissionDenied):
                render(self.parent.pk, f"pg:{action}:{self.child.pk}:0")
        ParentStudent.objects.create(parent=self.parent, student=self.child)
        self.child.is_active = False
        self.child.save()
        with self.assertRaises(PermissionDenied):
            services.child_profile(self.parent.pk, self.child.pk)

    def test_grade_and_attendance_history_are_scoped_to_child(self):
        own = self.grade()
        other_enrollment = Enrollment.objects.create(student=self.foreign, group=self.group, start_date="2050-01-02")
        self.grade(other_enrollment)
        attendance = Attendance.objects.create(student=self.child, lesson=self.lesson, status="late")
        Attendance.objects.create(student=self.foreign, lesson=self.lesson, status="absent")
        self.enrollment.status = "ended"
        self.enrollment.save()
        self.assertEqual([x.pk for x in services.child_grades(self.parent.pk, self.child.pk)[1]], [own.pk])
        self.assertEqual([x.pk for x in services.child_attendance(self.parent.pk, self.child.pk)[1]], [attendance.pk])

    def test_upcoming_respects_tashkent_enrollment_date(self):
        self.assertEqual(self.lesson.starts_at.date().isoformat(), "2050-01-01")
        _, lessons, _ = self.upcoming()
        self.assertEqual([l.pk for l in lessons], [self.lesson.pk])
        self.enrollment.start_date = "2050-01-03"
        self.enrollment.save()
        self.assertEqual(self.upcoming()[1], [])

    def test_upcoming_excludes_cancelled_past_and_other_child_lessons(self):
        Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now - timedelta(hours=2), ends_at=self.now - timedelta(hours=1))
        Lesson.objects.create(schedule=self.schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(hours=3), ends_at=self.now + timedelta(hours=4), status="cancelled")
        other = Enrollment.objects.create(student=self.foreign, subject=self.subject, teacher=self.teacher, start_date="2050-01-02")
        schedule = Schedule.objects.create(enrollment=other, weekday=6, start_time="04:00", end_time="05:00", valid_from="2050-01-02")
        Lesson.objects.create(schedule=schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(hours=5), ends_at=self.now + timedelta(hours=6))
        self.assertEqual([l.pk for l in self.upcoming()[1]], [self.lesson.pk])

    def test_individual_lessons_and_final_grades_are_supported(self):
        individual = Enrollment.objects.create(student=self.child, subject=self.subject, teacher=self.teacher, start_date="2050-01-02")
        schedule = Schedule.objects.create(enrollment=individual, weekday=6, start_time="04:00", end_time="05:00", valid_from="2050-01-02")
        lesson = Lesson.objects.create(schedule=schedule, teacher=self.teacher, subject=self.subject,
            starts_at=self.now + timedelta(hours=5), ends_at=self.now + timedelta(hours=6))
        self.assertEqual([l.pk for l in self.upcoming()[1]], [self.lesson.pk, lesson.pk])
        grade = self.grade(individual, lesson=False)
        self.assertEqual(services.child_grades(self.parent.pk, self.child.pk)[1][0].pk, grade.pk)

    def test_paused_or_expired_enrollment_has_no_future_lessons(self):
        self.enrollment.status = "paused"
        self.enrollment.save()
        self.assertEqual(self.upcoming()[1], [])
        self.enrollment.status = "active"
        self.enrollment.end_date = "2050-01-01"
        self.enrollment.save()
        self.assertEqual(self.upcoming()[1], [])

    def test_overlapping_enrollments_do_not_duplicate_lessons(self):
        Enrollment.objects.create(student=self.child, group=self.group, start_date="2050-01-02")
        self.assertEqual(len(self.upcoming()[1]), 1)

    def test_pagination_and_bad_pages(self):
        for number in range(7):
            child = Student.objects.create(full_name=f"Child {number}")
            ParentStudent.objects.create(parent=self.parent, student=child)
        first, more = services.parent_children(self.parent.pk)
        second, more2 = services.parent_children(self.parent.pk, 1)
        self.assertEqual((len(first), more, len(second), more2), (5, True, 3, False))
        self.assertFalse({c.pk for c in first} & {c.pk for c in second})
        with self.assertRaises(ValidationError):
            services.parent_children(self.parent.pk, -1)

    def test_parent_screens_escape_html_and_do_not_write(self):
        from bot.handlers.parent import render_parent_screen
        self.grade()
        Attendance.objects.create(student=self.child, lesson=self.lesson, status="present")
        before = (Grade.objects.count(), Attendance.objects.count(), Lesson.objects.count())
        render = async_to_sync(render_parent_screen)
        _, children = render(self.parent.pk, "pg:children:0")
        text, card = render(self.parent.pk, children.inline_keyboard[0][0].callback_data)
        self.assertIn("&lt;A&amp;B&gt;", text)
        for row in card.inline_keyboard[:3]:
            with patch("education.parent_services.timezone.now", return_value=self.now):
                text, _ = render(self.parent.pk, row[0].callback_data)
            self.assertIn("&lt;A&amp;B&gt;", text)
            self.assertLess(len(text), 4096)
        self.assertEqual(before, (Grade.objects.count(), Attendance.objects.count(), Lesson.objects.count()))

    def test_malformed_callback_data_is_rejected(self):
        from bot.handlers.parent import render_parent_screen
        for data in ["pg:children:-1", "pg:child:0", "pg:delete:1", "pg:grades:1:0:extra", "pg:children:999999999999"]:
            with self.assertRaises(ValueError):
                async_to_sync(render_parent_screen)(self.parent.pk, data)

    def test_main_menu_shows_only_assigned_roles(self):
        from bot.keyboards.main_menu import main_menu
        menu = async_to_sync(main_menu)(self.parent.pk)
        self.assertEqual([b.callback_data for row in menu.inline_keyboard for b in row], ["pg:children:0"])
        role = Role.objects.create(code=Role.TEACHER)
        UserRole.objects.create(user=self.parent, role=role)
        menu = async_to_sync(main_menu)(self.parent.pk)
        self.assertEqual([b.callback_data for row in menu.inline_keyboard for b in row], ["tg:groups:0", "pg:children:0"])
        self.parent.is_active = False
        self.parent.save()
        self.assertIsNone(async_to_sync(main_menu)(self.parent.pk))

    def test_grade_history_paginates_without_skipping_equal_dates(self):
        records = [self.grade() for _ in range(7)]
        _, first, more = services.child_grades(self.parent.pk, self.child.pk)
        _, second, more2 = services.child_grades(self.parent.pk, self.child.pk, 1)
        self.assertTrue(more)
        self.assertFalse(more2)
        self.assertEqual([x.pk for x in first + second], [x.pk for x in reversed(records)])

    def test_long_html_content_stays_within_telegram_message_limit(self):
        from bot.handlers.parent import render_parent_screen
        self.child.full_name = "<" * 255
        self.child.save()
        self.subject.name = "<" * 255
        self.subject.save()
        for _ in range(5):
            grade = self.grade()
            grade.value = "<" * 16
            grade.max_value = "<" * 16
            grade.save()
        text, _ = async_to_sync(render_parent_screen)(self.parent.pk, f"pg:grades:{self.child.pk}:0")
        self.assertLess(len(text), 4096)
        self.assertNotIn("<<", text)

    def test_future_enrollment_end_date_is_inclusive(self):
        self.enrollment.end_date = "2050-01-02"
        self.enrollment.save()
        self.assertEqual([l.pk for l in self.upcoming()[1]], [self.lesson.pk])
