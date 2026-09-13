from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model — обязателен с первой миграции (docs/django-apps.md, раздел 5).

    Поля telegram_id/full_name/phone/is_active/created_at/updated_at — из
    docs/database.md (утверждённая схема). `username`/`password`/`is_staff` —
    технические поля, нужные для стандартного Django-auth (в первую очередь
    для входа в Django Admin), не являются частью согласованной бизнес-схемы,
    но не противоречат ей — обычные пользователи (Teacher/Parent) их не
    используют вообще (username=None, unusable password).
    """

    username = models.CharField(
        max_length=150,
        unique=True,
        null=True,
        blank=True,
        help_text="Только для пользователей, которым нужен вход в Django Admin (в MVP — Admin).",
    )
    telegram_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Заполняется при привязке через InviteCode (Telegram User Linking).",
    )
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Доступ в Django Admin. Не путать с бизнес-ролью Admin (см. Role/UserRole).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users_user"
        constraints = [
            # UNIQUE(telegram_id) WHERE telegram_id IS NOT NULL — database.md, раздел 4
            models.UniqueConstraint(
                fields=["telegram_id"],
                condition=models.Q(telegram_id__isnull=False),
                name="uniq_user_telegram_id",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name or self.username or f"User#{self.pk}"


class Role(models.Model):
    """Справочник ролей. database.md, раздел 2 (User/Role design)."""

    ADMIN = "admin"
    TEACHER = "teacher"
    PARENT = "parent"

    CODE_CHOICES = [
        (ADMIN, "Admin"),
        (TEACHER, "Teacher"),
        (PARENT, "Parent"),
    ]

    code = models.CharField(max_length=32, unique=True, choices=CODE_CHOICES)

    class Meta:
        db_table = "users_role"

    def __str__(self) -> str:
        return self.get_code_display()


class UserRole(models.Model):
    """
    M2M User <-> Role через явную промежуточную модель — не голый ManyToManyField,
    потому что нам важно знать, кто и когда назначил роль (architecture.md,
    раздел 4: роль никогда не назначается пользователем самому себе).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roles_assigned",
        help_text="Кто назначил эту роль. NULL если назначивший позже удалён/деактивирован.",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_userrole"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_role"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.role}"
