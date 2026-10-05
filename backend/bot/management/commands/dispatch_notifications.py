"""Composition point: academic preparation + generic dispatcher + Telegram."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError

from bot.config import BOT_TOKEN
from education.notification_events import prepare_parent_notification
from notifications.dispatcher import DeliveryRejected, RetryLater, candidates, dispatch_batch


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
        parser.add_argument("--send", action="store_true")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--recipient-id", type=int)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 100:
            raise CommandError("--limit must be between 1 and 100.")
        if options["recipient_id"] is not None and options["recipient_id"] <= 0:
            raise CommandError("--recipient-id must be positive.")
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
        count = 0
        for item in candidates(options["recipient_id"])[:limit]:
            count += 1
            try:
                prepared = prepare_parent_notification(item)
            except DeliveryRejected as exc:
                self.stdout.write(f"#{item.pk} SKIP: {exc}")
            else:
                # ASCII escapes keep preview readable even in legacy Windows consoles.
                self.stdout.write(f"#{item.pk} user#{item.recipient_id}: {ascii(prepared.text)}")
        self.stdout.write(f"Previewed {count} items. Use --send only when ready to deliver.")
