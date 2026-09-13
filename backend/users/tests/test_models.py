from django.db import IntegrityError, transaction
from django.test import TestCase

from users.models import User


class UserModelTests(TestCase):
    def test_create_user_minimal(self):
        """Обычный пользователь (Teacher/Parent) создаётся без username/password/telegram_id."""
        user = User.objects.create_user(full_name="Иванова Мария")
        self.assertIsNone(user.username)
        self.assertIsNone(user.telegram_id)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            full_name="Admin User", username="admin", password="strong-pass-123"
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("strong-pass-123"))

    def test_telegram_id_uniqueness_enforced(self):
        """UNIQUE(telegram_id) WHERE telegram_id IS NOT NULL — database.md, раздел 4."""
        User.objects.create_user(full_name="Учитель 1", telegram_id=111111)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(full_name="Учитель 2 (дубль telegram_id)", telegram_id=111111)

    def test_multiple_users_without_telegram_id_allowed(self):
        """
        Partial unique index должен допускать сколько угодно NULL —
        это важно, потому что в MVP многие User создаются админом ДО того,
        как человек привяжет Telegram через InviteCode.
        """
        User.objects.create_user(full_name="Ожидает привязки 1")
        User.objects.create_user(full_name="Ожидает привязки 2")
        self.assertEqual(User.objects.filter(telegram_id__isnull=True).count(), 2)

    def test_multiple_users_without_username_allowed(self):
        """Аналогично — несколько User без username (Teacher/Parent без доступа в Admin)."""
        User.objects.create_user(full_name="Родитель 1")
        User.objects.create_user(full_name="Родитель 2")
        self.assertEqual(User.objects.filter(username__isnull=True).count(), 2)

    def test_deactivate_user(self):
        """
        is_active=False — основной механизм 'удаления' пользователя без
        потери истории (database.md, раздел 6, delete/history сводка).
        """
        user = User.objects.create_user(full_name="Уволенный сотрудник")
        user.is_active = False
        user.save(update_fields=["is_active"])

        refreshed = User.objects.get(pk=user.pk)
        self.assertFalse(refreshed.is_active)
        # Запись не удалена физически — она всё ещё существует в базе.
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
