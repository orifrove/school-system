from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from notifications.dispatcher import PreparedMessage
from notifications.models import Notification
from users.models import User
from bot.management.commands import dispatch_notifications as command


class NotificationCommandTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(full_name="Parent")
        self.item = Notification.objects.create(recipient=user, event_type="test", event_key="event", payload={})

    def test_default_preview_does_not_send_or_mutate(self):
        output = StringIO()
        with patch.object(command, "prepare_parent_notification", return_value=PreparedMessage(123, "Preview")), \
             patch.object(command, "telegram_sender") as sender:
            call_command("dispatch_notifications", stdout=output)
        sender.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "pending")
        self.assertEqual(self.item.retry_count, 0)
        self.assertIn("PREVIEW ONLY", output.getvalue())

    def test_send_requires_token(self):
        with patch.object(command, "BOT_TOKEN", ""):
            with self.assertRaises(CommandError):
                call_command("dispatch_notifications", send=True)

    def test_explicit_send_uses_dispatcher(self):
        with patch.object(command, "BOT_TOKEN", "fake"), \
             patch.object(command, "dispatch_batch", return_value={"retry_after": 0}) as dispatch:
            call_command("dispatch_notifications", send=True, limit=2, recipient_id=7, stdout=StringIO())
        dispatch.assert_called_once_with(command.telegram_sender, command.prepare_parent_notification, limit=2, recipient_id=7)

    def test_transport_sends_plain_text_with_timeout(self):
        bot = MagicMock()
        bot.__aenter__ = AsyncMock(return_value=bot)
        bot.__aexit__ = AsyncMock(return_value=False)
        bot.send_message = AsyncMock()
        with patch.object(command, "Bot", return_value=bot):
            command.telegram_sender(PreparedMessage(123, "<b>literal</b>"))
        bot.send_message.assert_awaited_once_with(chat_id=123, text="<b>literal</b>", parse_mode=None, request_timeout=10)

    def test_summary_counts_include_exhausted_but_exclude_other_channels(self):
        for key, status, attempts, channel in [("retry", "failed", 1, "telegram"),
                ("exhausted", "failed", 3, "telegram"), ("done", "sent", 0, "telegram"),
                ("email", "pending", 0, "email")]:
            Notification.objects.create(recipient=self.item.recipient, event_type="test", event_key=key,
                                        status=status, retry_count=attempts, channel=channel)
        output = StringIO()
        with patch.object(command, "prepare_parent_notification") as prepare, patch.object(command, "telegram_sender") as sender:
            call_command("dispatch_notifications", summary_only=True, stdout=output)
        prepare.assert_not_called()
        sender.assert_not_called()
        self.assertIn("total=4, pending=1, retryable=1, exhausted=1, sent=1", output.getvalue())

    def test_summary_respects_recipient_filter(self):
        other = User.objects.create_user(full_name="Other")
        Notification.objects.create(recipient=other, event_type="test", event_key="other")
        output = StringIO()
        call_command("dispatch_notifications", summary_only=True, recipient_id=self.item.recipient_id, stdout=output)
        self.assertIn("total=1", output.getvalue())

    def test_preview_explains_delay_and_blocked_items_without_preparing_or_mutating(self):
        self.item.payload = {"_delivery_not_before": timezone.now().timestamp() + 60}
        self.item.save()
        second = Notification.objects.create(recipient=self.item.recipient, event_type="test", event_key="second")
        before = list(Notification.objects.values())
        output = StringIO()
        with patch.object(command, "prepare_parent_notification") as prepare, patch.object(command, "telegram_sender") as sender:
            call_command("dispatch_notifications", stdout=output)
        prepare.assert_not_called()
        sender.assert_not_called()
        self.assertIn(f"#{self.item.pk} WAIT:", output.getvalue())
        self.assertIn(f"#{second.pk} BLOCKED:", output.getvalue())
        self.assertEqual(before, list(Notification.objects.values()))

    def test_expired_delay_is_ready_and_rejected_item_explains_reason(self):
        self.item.payload = {"_delivery_not_before": timezone.now().timestamp() - 1}
        self.item.save()
        output = StringIO()
        with patch.object(command, "prepare_parent_notification", return_value=PreparedMessage(123, "Ready")):
            call_command("dispatch_notifications", stdout=output)
        self.assertIn("READY", output.getvalue())
        with patch.object(command, "prepare_parent_notification", side_effect=command.DeliveryRejected("recipient_access_revoked")):
            call_command("dispatch_notifications", stdout=output)
        self.assertIn("SKIP: recipient_access_revoked", output.getvalue())

    def test_summary_and_send_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            call_command("dispatch_notifications", send=True, summary_only=True)
