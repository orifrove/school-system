from django import forms
from django.utils import timezone

from users.models import InviteCode


class InviteCodeAdminForm(forms.ModelForm):
    class Meta:
        model = InviteCode
        fields = "__all__"

    def clean(self):
        data = super().clean()
        status = data.get("status", self.instance.status)
        expires_at = data.get("expires_at", self.instance.expires_at)
        user = data.get("user", self.instance.user if self.instance.pk else None)
        if status == InviteCode.STATUS_ACTIVE:
            if expires_at is not None and expires_at <= timezone.now():
                self.add_error(None, "Активное приглашение должно истекать в будущем.")
            if self.instance.used_at is not None:
                self.add_error(None, "Использованное приглашение нельзя активировать повторно.")
            if user is not None and (not user.is_active or user.telegram_id is not None):
                self.add_error("user", "Выберите активного пользователя без Telegram-привязки.")
        return data
