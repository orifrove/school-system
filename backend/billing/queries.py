"""Read-only balances shared by the parent menu and Django Admin."""
from decimal import Decimal
from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Greatest


def with_balances(queryset):
    money = DecimalField(max_digits=20, decimal_places=2)
    zero = Value(Decimal("0.00"), output_field=money)
    return queryset.annotate(
        paid=Sum("payments__amount", default=Decimal("0.00"), output_field=money),
    ).annotate(
        outstanding=Greatest(F("amount_due") - F("paid"), zero, output_field=money),
        credit=Greatest(F("paid") - F("amount_due"), zero, output_field=money),
    )
