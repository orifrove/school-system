"""Explicitly started polling worker for the existing bounded dispatcher."""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from bot.management.commands.dispatch_notifications import telegram_sender
from bot.config import BOT_TOKEN
from education.notification_events import prepare_parent_notification
from notifications.dispatcher import dispatch_batch


class Command(BaseCommand):
    help = "Process notification batches until Ctrl+C. Requires --send; does not start with run_bot."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--interval", type=int, default=15)
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--recipient-id", type=int)
        parser.add_argument("--max-batches", type=int, default=0, help="Stop after N batches; 0 runs until stopped.")

    def handle(self, *args, **options):
        if not options["send"]:
            raise CommandError("No delivery started. Use dispatch_notifications for preview, or explicitly pass --send.")
        if not BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")
        if not 1 <= options["interval"] <= 3600:
            raise CommandError("--interval must be between 1 and 3600 seconds.")
        if not 1 <= options["limit"] <= 100:
            raise CommandError("--limit must be between 1 and 100.")
        if options["max_batches"] < 0:
            raise CommandError("--max-batches must be nonnegative.")
        if options["recipient_id"] is not None and options["recipient_id"] <= 0:
            raise CommandError("--recipient-id must be positive.")
        self.stdout.write("Notification worker started. Delivery enabled. Stop with Ctrl+C.")
        batch = 0
        try:
            while True:
                close_old_connections()
                report = dispatch_batch(telegram_sender, prepare_parent_notification,
                    limit=options["limit"], recipient_id=options["recipient_id"])
                batch += 1
                if any(report.values()):
                    self.stdout.write(f"Batch {batch}: {report}")
                if options["max_batches"] and batch >= options["max_batches"]:
                    self.stdout.write(f"Stopped after {batch} batches.")
                    return
                close_old_connections()
                time.sleep(max(options["interval"], report["retry_after"]))
        except KeyboardInterrupt:
            self.stdout.write("Notification worker stopped.")
        except Exception:
            # Stop on infrastructure failures instead of spinning or exposing token URLs.
            raise CommandError("Notification worker failed; stopped. Check database availability and server configuration.") from None
        finally:
            close_old_connections()
