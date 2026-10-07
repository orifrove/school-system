from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode

from .forms import BillingPeriodAdminForm, PaymentAdminForm
from .models import BillingPeriod, Payment
from .queries import with_balances


class BalanceFilter(admin.SimpleListFilter):
    title = "состояние оплаты"
    parameter_name = "balance"

    def lookups(self, request, model_admin):
        return (("unpaid", "Не оплачено"), ("partial", "Частично оплачено"),
                ("paid", "Оплачено"), ("credit", "Есть переплата"))

    def queryset(self, request, queryset):
        if self.value() == "unpaid":
            return queryset.filter(paid=0, outstanding__gt=0)
        if self.value() == "partial":
            return queryset.filter(paid__gt=0, outstanding__gt=0)
        if self.value() == "paid":
            return queryset.filter(outstanding=0)
        if self.value() == "credit":
            return queryset.filter(credit__gt=0)
        return queryset


class PaymentHistoryInline(admin.TabularInline):
    model = Payment
    fields = ("amount", "paid_at", "registered_by", "comment")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("registered_by").order_by("-paid_at", "-pk")


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    change_form_template = "admin/billing/billingperiod/change_form.html"
    form = BillingPeriodAdminForm
    list_display = ("id", "enrollment", "period_start", "period_end", "amount_due",
                    "paid_amount", "remaining_amount", "credit_amount", "balance_status")
    list_filter = (BalanceFilter,)
    search_fields = ("enrollment__student__full_name", "enrollment__group__name")
    autocomplete_fields = ("enrollment",)
    exclude = ("status",)
    readonly_fields = ("created_at", "paid_amount", "remaining_amount", "credit_amount", "balance_status")
    inlines = (PaymentHistoryInline,)
    date_hierarchy = "period_start"
    ordering = ("-period_start", "-pk")
    list_per_page = 30

    def change_view(self, request, object_id, form_url="", extra_context=None):
        context = dict(extra_context or {})
        payment_admin = self.admin_site._registry.get(Payment)
        if payment_admin and payment_admin.has_add_permission(request):
            context["register_payment_url"] = (
                reverse("admin:billing_payment_add", current_app=self.admin_site.name)
                + "?" + urlencode({"billing_period": object_id})
            )
        return super().change_view(request, object_id, form_url, context)

    def get_queryset(self, request):
        return with_balances(super().get_queryset(request)).select_related(
            "enrollment__student", "enrollment__group", "enrollment__subject", "enrollment__teacher")

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("enrollment", "period_start", "period_end", "amount_due") if obj else ())

    @admin.display(description="Внесено", ordering="paid")
    def paid_amount(self, obj):
        return getattr(obj, "paid", None)

    @admin.display(description="Остаток", ordering="outstanding")
    def remaining_amount(self, obj):
        return getattr(obj, "outstanding", None)

    @admin.display(description="Переплата", ordering="credit")
    def credit_amount(self, obj):
        return getattr(obj, "credit", None)

    @admin.display(description="Состояние оплаты")
    def balance_status(self, obj):
        if not hasattr(obj, "outstanding"):
            return "—"
        if obj.outstanding == 0:
            return "Оплачено"
        return "Частично оплачено" if obj.paid else "Не оплачено"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    list_display = ("id", "billing_period", "amount", "paid_at", "registered_by")
    autocomplete_fields = ("billing_period",)
    readonly_fields = ("registered_by", "created_at")
    search_fields = ("billing_period__enrollment__student__full_name", "comment")
    date_hierarchy = "paid_at"
    ordering = ("-paid_at", "-pk")
    list_per_page = 30

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("registered_by", "billing_period__enrollment__student",
            "billing_period__enrollment__group", "billing_period__enrollment__subject", "billing_period__enrollment__teacher")

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("paid_at", timezone.now())
        period_id = request.GET.get("billing_period", "")
        # URL parameters are untrusted; only prefill an accessible, existing period.
        initial.pop("billing_period", None)
        period_admin = self.admin_site._registry.get(BillingPeriod)
        if (period_admin and period_id.isascii() and period_id.isdecimal()
                and len(period_id) <= 18):
            period = period_admin.get_queryset(request).filter(pk=int(period_id)).first()
            if period and period_admin.has_view_or_change_permission(request, period):
                initial["billing_period"] = period.pk
                if period.outstanding > 0:
                    initial.setdefault("amount", period.outstanding)
        return initial

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registered_by = request.user
        super().save_model(request, obj, form, change)
