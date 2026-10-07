from django import forms
from .models import BillingPeriod, Payment


class BillingPeriodAdminForm(forms.ModelForm):
    class Meta:
        model = BillingPeriod
        fields = "__all__"

    def clean(self):
        data = super().clean()
        start, end = data.get("period_start"), data.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "Конец периода не может быть раньше начала.")
        amount = data.get("amount_due")
        if amount is not None and amount < 0:
            self.add_error("amount_due", "Начисление не может быть отрицательным.")
        return data


class PaymentAdminForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = "__all__"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Сумма платежа должна быть больше нуля.")
        return amount
