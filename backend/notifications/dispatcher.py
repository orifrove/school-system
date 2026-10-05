"""Bounded synchronous outbox dispatcher with injected preparation and transport.

    Row locks prevent two workers from sending the same item concurrently.
    Delivery is at-least-once: a crash after Telegram accepts a message but
    before the database commit can still result in a duplicate on retry.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from notifications.models import Notification

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class PreparedMessage:
    chat_id: int
    text: str


class DeliveryRejected(Exception):
    """Permanent rejection; message must not be retried automatically."""


class RetryLater(Exception):
    def __init__(self, seconds):
        self.seconds = max(1, int(seconds))


def candidates(recipient_id=None):
    queryset = Notification.objects.filter(channel="telegram",
        status__in=[Notification.STATUS_PENDING, Notification.STATUS_FAILED], retry_count__lt=MAX_ATTEMPTS)
    if recipient_id is not None:
        queryset = queryset.filter(recipient_id=recipient_id)
    return queryset.order_by("created_at", "pk")


def dispatch_batch(sender, prepare, *, limit=50, recipient_id=None):
    if not 1 <= limit <= 100:
        raise ValueError("Batch limit must be between 1 and 100.")
    report = {"sent": 0, "failed": 0, "skipped": 0, "retry_after": 0}
    ids = list(candidates(recipient_id).values_list("pk", flat=True)[:limit])
    for notification_id in ids:
        # Keep this transaction short: the transport must have a bounded timeout.
        with transaction.atomic():
            item = candidates(recipient_id).select_for_update(skip_locked=True).filter(pk=notification_id).first()
            if item is None:
                report["skipped"] += 1
                continue
            payload = item.payload if isinstance(item.payload, dict) else {}
            wait_until = payload.get("_delivery_not_before", 0)
            if isinstance(wait_until, (int, float)) and wait_until > timezone.now().timestamp():
                report["retry_after"] = int(wait_until - timezone.now().timestamp()) + 1
                break
            try:
                prepared = prepare(item)
                sender(prepared)
            except RetryLater as exc:
                item.payload = {**payload, "_delivery_not_before": timezone.now().timestamp() + exc.seconds}
                item.error = "rate_limited"
                item.save(update_fields=["payload", "error"])
                report["retry_after"] = exc.seconds
                break
            except DeliveryRejected as exc:
                item.status = Notification.STATUS_FAILED
                item.retry_count = MAX_ATTEMPTS
                # Reasons are controlled codes, never raw HTTP exceptions/token URLs.
                item.error = str(exc)[:255]
                report["failed"] += 1
            except Exception:
                item.status = Notification.STATUS_FAILED
                item.retry_count += 1
                item.error = "delivery_failed"
                report["failed"] += 1
            else:
                item.status = Notification.STATUS_SENT
                item.sent_at = timezone.now()
                item.error = None
                item.payload = {key: value for key, value in payload.items() if key != "_delivery_not_before"}
                report["sent"] += 1
            item.save(update_fields=["status", "retry_count", "error", "sent_at", "payload"])
    return report
