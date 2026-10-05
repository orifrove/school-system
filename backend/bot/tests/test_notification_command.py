from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import TestCase

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
