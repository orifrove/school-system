"""Generic idempotent outbox; academic rules live in the caller's app."""

from django.core.exceptions import ValidationError

from notifications.models import Notification


def notify(recipient, event_type, event_key, payload):
    if not event_key or len(event_key) > 255 or not event_type or len(event_type) > 64:
        raise ValidationError("Invalid notification event key or type.")
    if not isinstance(payload, dict):
        raise ValidationError("Notification payload must be a dictionary.")
    notification, _ = Notification.objects.get_or_create(
        recipient=recipient, event_key=event_key,
        defaults={"event_type": event_type, "payload": payload},
    )
    return notification
