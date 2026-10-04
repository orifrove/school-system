"""Operations for linking pre-created users to Telegram."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import InviteCode, User


def activate_invite_code(code_text: str, telegram_id: int) -> str:
    """Consume an invite and link its user in one transaction.

    Locking prevents two callers from consuming the same invite. The unique
    Telegram constraint arbitrates concurrent claims through different codes.
    Existing links must never be overwritten by an invitation.
    """
    if not code_text or len(code_text) > 64 or telegram_id <= 0:
        return "not_found"
    try:
        with transaction.atomic():
            invite = InviteCode.objects.select_for_update().filter(code=code_text).first()
            if invite is None or invite.status == InviteCode.STATUS_INVALIDATED:
                return "not_found"
            if invite.status == InviteCode.STATUS_USED or invite.used_at is not None:
                return "used"
            now = timezone.now()
            if invite.expires_at <= now:
                return "expired"
            user = User.objects.select_for_update().get(pk=invite.user_id)
            if not user.is_active:
                return "inactive"
            if user.telegram_id is not None or User.objects.filter(telegram_id=telegram_id).exists():
                return "already_linked"
            user.telegram_id = telegram_id
            user.save(update_fields=["telegram_id"])
            invite.status = InviteCode.STATUS_USED
            invite.used_at = now
            invite.save(update_fields=["status", "used_at"])
    except IntegrityError as exc:
        # Do not mask unrelated database failures.
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) != "uniq_user_telegram_id":
            raise
        return "already_linked"
    return "ok"
