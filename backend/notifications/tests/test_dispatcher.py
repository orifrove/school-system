from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import Mock, patch

from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from notifications.dispatcher import DeliveryRejected, PreparedMessage, RetryLater, dispatch_batch
from notifications.models import Notification
from notifications.services import notify
from users.models import User


def prepare(item):
    return PreparedMessage(123, "Test")


class DispatcherTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(full_name="Parent")
        self.item = notify(self.user, "test", "event:1", {})

    def test_success_and_repeat_dispatch(self):
        sender = Mock()
        report = dispatch_batch(sender, prepare)
        self.assertEqual(report["sent"], 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "sent")
        self.assertIsNotNone(self.item.sent_at)
        dispatch_batch(sender, prepare)
        sender.assert_called_once_with(PreparedMessage(123, "Test"))

    def test_notify_is_idempotent_and_does_not_reset_sent_event(self):
        dispatch_batch(Mock(), prepare)
        again = notify(self.user, "test", "event:1", {"changed": True})
        self.assertEqual(again.pk, self.item.pk)
        self.assertEqual(again.status, "sent")
        self.assertEqual(again.payload, {})

    def test_transient_failure_stops_after_three_attempts_and_hides_exception(self):
        sender = Mock(side_effect=RuntimeError("https://secret-token.example"))
        for _ in range(4):
            dispatch_batch(sender, prepare)
        self.assertEqual(sender.call_count, 3)
        self.item.refresh_from_db()
        self.assertEqual(self.item.retry_count, 3)
        self.assertEqual(self.item.error, "delivery_failed")

    def test_rejected_recipient_never_reaches_transport(self):
        sender = Mock()
        dispatch_batch(sender, Mock(side_effect=DeliveryRejected("recipient_access_revoked")))
        sender.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "failed")
        self.assertEqual(self.item.retry_count, 3)

    def test_rate_limit_pauses_batch_and_respects_retry_time(self):
        notify(self.user, "test", "event:2", {})
        sender = Mock(side_effect=RetryLater(30))
        report = dispatch_batch(sender, prepare)
        self.assertEqual(report["retry_after"], 30)
        sender.assert_called_once()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "pending")
        sender.reset_mock()
        dispatch_batch(sender, prepare)
        sender.assert_not_called()
        with patch("notifications.dispatcher.timezone.now", return_value=timezone.now() + timedelta(seconds=31)):
            report = dispatch_batch(Mock(), prepare)
        self.assertEqual(report["sent"], 2)

    def test_recipient_filter_limit_and_other_channels(self):
        other = User.objects.create_user(full_name="Other")
        notify(other, "test", "other", {})
        second = notify(self.user, "test", "event:2", {})
        second.channel = "email"
        second.save()
        sender = Mock()
        self.assertEqual(dispatch_batch(sender, prepare, recipient_id=self.user.pk, limit=1)["sent"], 1)
        sender.assert_called_once()
        self.assertEqual(Notification.objects.filter(status="pending").count(), 2)
        with self.assertRaises(ValueError):
            dispatch_batch(sender, prepare, limit=0)


class ConcurrentDispatcherTests(TransactionTestCase):
    def test_workers_do_not_send_same_row_concurrently(self):
        user = User.objects.create_user(full_name="Parent")
        notify(user, "test", "event", {})
        entered, release = Event(), Event()

        def first_sender(message):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Timed out")

        def run(sender):
            close_old_connections()
            try:
                return dispatch_batch(sender, prepare)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, first_sender)
            try:
                self.assertTrue(entered.wait(5))
                other_sender = Mock()
                second = pool.submit(run, other_sender).result(timeout=5)
                other_sender.assert_not_called()
                self.assertEqual(second["skipped"], 1)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)["sent"], 1)
