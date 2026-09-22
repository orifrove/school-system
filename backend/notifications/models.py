from django.db import models


class Notification(models.Model):
    """
    Запись уведомления. database.md v4, раздел 11; architecture.md,
    раздел 7 (NotificationService → Notification → Dispatcher → Telegram).

    Намеренно НЕ знает ничего про Lesson/Grade/BillingPeriod и т.д. —
    получает от вызывающей стороны (education.services, billing.services)
    уже готовые event_type и payload (обычный dict с текстовыми полями
    для рендера сообщения). Это то самое разделение из django-apps.md,
    раздел 3: education/billing зависят от notifications (вызывают
    notify()), но notifications никогда не импортирует их обратно —
    иначе был бы circular import.

    event_key — детерминированный ключ конкретного бизнес-события
    (например "attendance_absent:lesson_42:student_17"). UNIQUE(recipient,
    event_key) физически не даёт создать дубль уведомления на уровне БД,
    не полагаясь только на "обещание не вызывать notify() дважды".
    """

    recipient = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=64)
    event_key = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    channel = models.CharField(max_length=32, default="telegram")

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.CharField(max_length=255, null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        constraints = [
            models.UniqueConstraint(fields=["recipient", "event_key"], name="uniq_notification_recipient_event_key"),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="idx_notif_status_created"),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} — {self.event_type} — {self.status}"