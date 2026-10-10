from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase

from bot.management.commands import run_notification_worker as worker


class NotificationWorkerTests(SimpleTestCase):
    def setUp(self):
        self.report = {"sent": 0, "failed": 0, "skipped": 0, "retry_after": 0}

    def run_worker(self, **kwargs):
        output = StringIO()
        call_command("run_notification_worker", stdout=output, **kwargs)
        return output.getvalue()

    def test_delivery_requires_explicit_flag(self):
        with patch.object(worker, "dispatch_batch") as dispatch:
            with self.assertRaises(CommandError):
                self.run_worker()
        dispatch.assert_not_called()

    def test_invalid_options_and_missing_token_fail_before_dispatch(self):
        with patch.object(worker, "BOT_TOKEN", "fake"), patch.object(worker, "dispatch_batch") as dispatch:
            for options in [{"interval": 0}, {"interval": 3601}, {"limit": 101}, {"max_batches": -1}, {"recipient_id": 0}]:
                with self.assertRaises(CommandError):
                    self.run_worker(send=True, **options)
            dispatch.assert_not_called()
        with patch.object(worker, "BOT_TOKEN", ""):
            with self.assertRaises(CommandError):
                self.run_worker(send=True)

    def test_bounded_run_passes_filters_and_does_not_sleep_after_last_batch(self):
        with patch.object(worker, "BOT_TOKEN", "fake"), patch.object(worker, "dispatch_batch", return_value=self.report) as dispatch, \
             patch.object(worker.time, "sleep") as sleep, patch.object(worker, "close_old_connections"):
            output = self.run_worker(send=True, max_batches=2, interval=7, limit=3, recipient_id=2)
        self.assertEqual(dispatch.call_count, 2)
        dispatch.assert_called_with(worker.telegram_sender, worker.prepare_parent_notification, limit=3, recipient_id=2)
        sleep.assert_called_once_with(7)
        self.assertIn("Stopped after 2 batches", output)

    def test_rate_limit_wait_is_respected(self):
        delayed = dict(self.report, retry_after=60)
        with patch.object(worker, "BOT_TOKEN", "fake"), patch.object(worker, "dispatch_batch", side_effect=[delayed, self.report]), \
             patch.object(worker.time, "sleep") as sleep, patch.object(worker, "close_old_connections"):
            self.run_worker(send=True, max_batches=2, interval=5)
        sleep.assert_called_once_with(60)

    def test_keyboard_interrupt_stops_cleanly(self):
        with patch.object(worker, "BOT_TOKEN", "fake"), patch.object(worker, "dispatch_batch", return_value=self.report), \
             patch.object(worker.time, "sleep", side_effect=KeyboardInterrupt), patch.object(worker, "close_old_connections"):
            output = self.run_worker(send=True)
        self.assertIn("worker stopped", output)

    def test_infrastructure_error_stops_without_exposing_exception(self):
        with patch.object(worker, "BOT_TOKEN", "fake"), patch.object(worker, "dispatch_batch", side_effect=RuntimeError("SECRET_URL")) as dispatch, \
             patch.object(worker.time, "sleep") as sleep, patch.object(worker, "close_old_connections"):
            with self.assertRaises(CommandError) as error:
                self.run_worker(send=True)
        self.assertNotIn("SECRET_URL", str(error.exception))
        self.assertEqual(dispatch.call_count, 1)
        sleep.assert_not_called()
