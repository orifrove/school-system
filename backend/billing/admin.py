from django.contrib import admin

from .models import BillingPeriod, Payment


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ("id", "enrollment", "period_start", "period_end", "amount_due", "status")
    list_filter = ("status",)
    search_fields = ("enrollment__student__full_name",)
    autocomplete_fields = ("enrollment",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "billing_period", "amount", "paid_at", "registered_by")
    autocomplete_fields = ("billing_period", "registered_by")