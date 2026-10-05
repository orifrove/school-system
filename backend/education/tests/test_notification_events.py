from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from education import notification_events, services
from education.models import Attendance, Grade, ParentStudent
from education.tests import test_teacher_services as fixtures
from notifications.dispatcher import DeliveryRejected
from notifications.models import Notification
from users.models import Role, User, UserRole


class AcademicNotificationTests(TestCase):
    def setUp(self):
        fixtures.TeacherServicesTests.setUp(self)
        self.parent = User.objects.create_user(full_name="Parent", telegram_id=12345)
        self.parent_role = Role.objects.create(code=Role.PARENT)
        UserRole.objects.create(user=self.parent, role=self.parent_role)
        self.link = ParentStudent.objects.create(parent=self.parent, student=self.student)

    def grade(self):
        return services.add_grade(self.enrollment, self.teacher, "5", lesson=self.lesson, given_at=timezone.now())

    def mark(self, status="present"):
        return services.mark_attendance(self.lesson, self.student, status, marked_by=self.teacher)

    def test_grade_enqueues_once_per_parent(self):
        other = User.objects.create_user(full_name="Other parent", telegram_id=23456)
        UserRole.objects.create(user=other, role=self.parent_role)
        ParentStudent.objects.create(parent=other, student=self.student)
        grade = self.grade()
        notification_events.queue_grade(grade)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertCountEqual(Notification.objects.values_list("recipient_id", flat=True), [self.parent.pk, other.pk])
        prepared = notification_events.prepare_parent_notification(Notification.objects.get(recipient=self.parent))
        self.assertEqual(prepared.chat_id, 12345)
        self.assertIn("Оценка: 5", prepared.text)
        self.assertIn(self.student.full_name, prepared.text)

    def test_no_queue_for_ineligible_recipients(self):
        for field, value in [("is_active", False), ("telegram_id", None)]:
            original = getattr(self.parent, field)
            setattr(self.parent, field, value)
            self.parent.save()
            self.grade()
            setattr(self.parent, field, original)
            self.parent.save()
        UserRole.objects.filter(user=self.parent).delete()
        self.grade()
        self.assertFalse(Notification.objects.exists())

    def test_same_attendance_is_a_noop_but_correction_queues_new_event(self):
        first = self.mark("absent")
        again = self.mark("absent")
        self.assertEqual(first.updated_at, again.updated_at)
        self.assertEqual(Notification.objects.count(), 1)
        self.mark("present")
        self.assertEqual(Notification.objects.count(), 2)
        with self.assertRaisesMessage(DeliveryRejected, "superseded"):
            notification_events.prepare_parent_notification(Notification.objects.earliest("pk"))
        prepared = notification_events.prepare_parent_notification(Notification.objects.latest("pk"))
        self.assertIn("Присутствовал", prepared.text)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_failed_enqueue_rolls_back_grade_and_attendance(self):
        with patch("education.notification_events.notify", side_effect=RuntimeError("outbox failed")):
            with self.assertRaises(RuntimeError):
                self.grade()
            with self.assertRaises(RuntimeError):
                self.mark()
        self.assertFalse(Grade.objects.exists())
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_revoked_link_prevents_delivery(self):
        self.grade()
        self.link.delete()
        with self.assertRaisesMessage(DeliveryRejected, "recipient_access_revoked"):
            notification_events.prepare_parent_notification(Notification.objects.get())

    def test_role_removed_after_queue_prevents_delivery(self):
        self.grade()
        UserRole.objects.filter(user=self.parent).delete()
        with self.assertRaises(DeliveryRejected):
            notification_events.prepare_parent_notification(Notification.objects.get())

    def test_deleted_grade_and_disabled_student_prevent_delivery(self):
        grade = self.grade()
        item = Notification.objects.get()
        grade.delete()
        with self.assertRaisesMessage(DeliveryRejected, "record_unavailable"):
            notification_events.prepare_parent_notification(item)
        self.student.is_active = False
        self.student.save()
        with self.assertRaisesMessage(DeliveryRejected, "student_unavailable"):
            notification_events.prepare_parent_notification(item)

    def test_missing_or_mismatched_payload_is_rejected(self):
        self.grade()
        item = Notification.objects.get()
        for payload in [{}, [], {"student_id": str(self.student.pk)}, {"student_id": self.student.pk, "grade_id": 999999}]:
            item.payload = payload
            with self.assertRaises(DeliveryRejected):
                notification_events.prepare_parent_notification(item)
