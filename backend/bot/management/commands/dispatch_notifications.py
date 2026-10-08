"""Composition point: academic preparation + generic dispatcher + Telegram."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from bot.config import BOT_TOKEN
from education.notification_events import prepare_parent_notification
from notifications.dispatcher import DeliveryRejected, RetryLater, candidates, dispatch_batch, retry_delay, MAX_ATTEMPTS
from notifications.models import Notification


def telegram_sender(prepared):
    async def send():
        async with Bot(token=BOT_TOKEN) as bot:
            try:
                await bot.send_message(chat_id=prepared.chat_id, text=prepared.text,
                                       parse_mode=None, request_timeout=10)
            except TelegramRetryAfter as exc:
                raise RetryLater(exc.retry_after) from None
            except (TelegramForbiddenError, TelegramBadRequest):
                raise DeliveryRejected("telegram_rejected") from None
    async_to_sync(send)()


class Command(BaseCommand):
    help = "Preview parent notification outbox; --send explicitly enables a bounded delivery batch."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--send", action="store_true")
        mode.add_argument("--summary-only", action="store_true", help="Show queue counts without message text or delivery.")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--recipient-id", type=int)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 100:
            raise CommandError("--limit must be between 1 and 100.")
        if options["recipient_id"] is not None and options["recipient_id"] <= 0:
            raise CommandError("--recipient-id must be positive.")
        if options["send"] and options["summary_only"]:
            raise CommandError("--send and --summary-only cannot be combined.")
        if options["send"]:
            if not BOT_TOKEN:
                raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")
            report = dispatch_batch(telegram_sender, prepare_parent_notification,
                                    limit=limit, recipient_id=options["recipient_id"])
            self.stdout.write(str(report))
            if report["retry_after"]:
                self.stdout.write(f"Rate limited. Wait at least {report['retry_after']} seconds before retrying.")
            return
        self.stdout.write("PREVIEW ONLY: no messages will be sent and no records will be changed.")
        queue = Notification.objects.filter(channel="telegram")
        if options["recipient_id"] is not None:
            queue = queue.filter(recipient_id=options["recipient_id"])
        counts = queue.aggregate(
            total=Count("pk"),
            pending=Count("pk", filter=Q(status="pending", retry_count__lt=MAX_ATTEMPTS)),
            retryable=Count("pk", filter=Q(status="failed", retry_count__lt=MAX_ATTEMPTS)),
            exhausted=Count("pk", filter=Q(status__in=["pending", "failed"], retry_count__gte=MAX_ATTEMPTS)),
            sent=Count("pk", filter=Q(status="sent")),
        )
        self.stdout.write("Telegram queue: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        self.stdout.write("Pending/retryable counts may include delayed or no-longer-valid items.")
        if options["summary_only"]:
            return
        count = 0
        batch_paused = False
        for item in candidates(options["recipient_id"])[:limit]:
            count += 1
            if batch_paused:
                self.stdout.write(f"#{item.pk} BLOCKED: earlier item pauses this batch.")
                continue
            delay = retry_delay(item)
            if delay:
                self.stdout.write(f"#{item.pk} WAIT: retry in {delay} seconds; delivery would pause this batch.")
                batch_paused = True
                continue
            try:
                prepared = prepare_parent_notification(item)
            except DeliveryRejected as exc:
                self.stdout.write(f"#{item.pk} SKIP: {exc}")
            else:
                # ASCII escapes keep preview readable even in legacy Windows consoles.
                self.stdout.write(f"#{item.pk} READY user#{item.recipient_id}: {ascii(prepared.text)}")
        self.stdout.write(f"Previewed {count} items. Use --send only when ready to deliver.")
