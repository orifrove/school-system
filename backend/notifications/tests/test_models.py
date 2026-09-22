from django.db import IntegrityError, transaction
from django.test import TestCase

from notifications.models import Notification
from users.models import User


class NotificationModelTests(TestCase):
    def setUp(self):
        self.parent = User.objects.create_user(full_name="Родитель Гусев")

    def test_create_notification(self):
        notification = Notification.objects.create(
            recipient=self.parent,
            event_type="attendance_absent",
            event_key="attendance_absent:lesson_1:student_1",
            payload={"subject": "Математика", "date": "2026-09-21"},
        )
        self.assertEqual(notification.status, Notification.STATUS_PENDING)
        self.assertEqual(notification.retry_count, 0)

    def test_idempotency_same_event_key_rejected(self):
        """
        database.md, раздел 11: UNIQUE(recipient, event_key) физически
        не даёт создать дубль уведомления на уровне БД.
        """
        Notification.objects.create(
            recipient=self.parent,
            event_type="attendance_absent",
            event_key="attendance_absent:lesson_1:student_1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Notification.objects.create(
                    recipient=self.parent,
                    event_type="attendance_absent",
                    event_key="attendance_absent:lesson_1:student_1",
                )

    def test_same_event_key_allowed_for_different_recipients(self):
        """Тот же event_key, но другой получатель — не конфликт."""
        other_parent = User.objects.create_user(full_name="Родитель Волкова")

        Notification.objects.create(
            recipient=self.parent,
            event_type="attendance_absent",
            event_key="attendance_absent:lesson_1:student_1",
        )
        notification2 = Notification.objects.create(
            recipient=other_parent,
            event_type="attendance_absent",
            event_key="attendance_absent:lesson_1:student_1",
        )
        self.assertIsNotNone(notification2.id)

    def test_deleting_recipient_cascades_to_notification(self):
        """CASCADE — уведомление без получателя не имеет смысла."""
        notification = Notification.objects.create(
            recipient=self.parent,
            event_type="new_grade",
            event_key="new_grade:1",
        )
        notification_id = notification.id

        self.parent.delete()

        self.assertFalse(Notification.objects.filter(id=notification_id).exists())

    def test_payload_defaults_to_empty_dict(self):
        notification = Notification.objects.create(
            recipient=self.parent,
            event_type="payment_due",
            event_key="payment_due:1",
        )
        self.assertEqual(notification.payload, {})