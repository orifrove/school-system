from django.db import models


class BillingPeriod(models.Model):
    """
    Период оплаты для конкретного Enrollment. database.md v4, раздел 8.

    amount_due — ЗАФИКСИРОВАННЫЙ snapshot суммы на этот период,
    вычисляется ОДИН РАЗ при создании (из Enrollment.price_override
    или дефолтной цены на тот момент) и никогда не пересчитывается
    автоматически. Изменение Enrollment.price_override влияет только
    на будущие BillingPeriod — структурная гарантия, не процедурная:
    здесь нет FK-зависимости от price_override, просто скопированное
    число, поэтому "случайно" пересчитаться не может даже теоретически.
    """

    enrollment = models.ForeignKey(
        "education.Enrollment",
        on_delete=models.PROTECT,
        related_name="billing_periods",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)

    STATUS_UNPAID = "unpaid"
    STATUS_PARTIALLY_PAID = "partially_paid"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_UNPAID, "Unpaid"),
        (STATUS_PARTIALLY_PAID, "Partially paid"),
        (STATUS_PAID, "Paid"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_billingperiod"
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "period_start", "period_end"],
                name="uniq_billingperiod_enrollment_period",
            ),
            models.CheckConstraint(condition=models.Q(amount_due__gte=0), name="billingperiod_amount_due_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.enrollment} — {self.period_start}–{self.period_end}"




class Payment(models.Model):
    """
    Факт платежа. database.md v4, раздел 8.

    Многие Payment могут закрывать один BillingPeriod (частичная
    оплата, несколько платежей) — 1:N к BillingPeriod, не наоборот.
    """

    billing_period = models.ForeignKey(
        "billing.BillingPeriod",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_at = models.DateTimeField()
    registered_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payments_registered",
        help_text="Кто из админов внёс платёж вручную.",
    )
    comment = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_payment"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.billing_period} — {self.amount}"