from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from users.models import InviteCode, User


class InviteCodeModelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(full_name="Админ Центра")
        self.pending_teacher = User.objects.create_user(full_name="Ожидает привязки Учитель")

    def test_create_invite_code(self):
        code = InviteCode.objects.create(
            code="ABC123",
            user=self.pending_teacher,
            created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        self.assertEqual(code.status, InviteCode.STATUS_ACTIVE)
        self.assertIsNone(code.used_at)

    def test_code_uniqueness(self):
        InviteCode.objects.create(
            code="ABC123", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        other_user = User.objects.create_user(full_name="Другой Ожидающий")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InviteCode.objects.create(
                    code="ABC123", user=other_user, created_by=self.admin,
                    expires_at=parse_datetime("2026-12-31T00:00:00Z"),
                )

    def test_cannot_have_two_active_codes_for_same_user(self):
        """
        database.md, раздел 12: у User максимум один активный код.
        Партиальный UniqueConstraint (status='active').
        """
        InviteCode.objects.create(
            code="CODE1", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InviteCode.objects.create(
                    code="CODE2", user=self.pending_teacher, created_by=self.admin,
                    expires_at=parse_datetime("2026-12-31T00:00:00Z"),
                )

    def test_regenerate_code_after_invalidating_old_one(self):
        """
        database.md, раздел 12: потерянный код -> старый invalidated,
        новый активный для того же User -> должно быть разрешено.
        """
        old_code = InviteCode.objects.create(
            code="OLD123", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        old_code.status = InviteCode.STATUS_INVALIDATED
        old_code.save(update_fields=["status"])

        new_code = InviteCode.objects.create(
            code="NEW456", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        self.assertEqual(new_code.status, InviteCode.STATUS_ACTIVE)

    def test_using_code_marks_it_used(self):
        code = InviteCode.objects.create(
            code="USE123", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        code.status = InviteCode.STATUS_USED
        code.used_at = timezone.now()
        code.save(update_fields=["status", "used_at"])

        code.refresh_from_db()
        self.assertEqual(code.status, InviteCode.STATUS_USED)
        self.assertIsNotNone(code.used_at)

    def test_cannot_delete_admin_who_created_codes(self):
        from django.db.models import ProtectedError

        InviteCode.objects.create(
            code="PROT123", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        with self.assertRaises(ProtectedError):
            self.admin.delete()

    def test_deleting_user_cascades_to_invite_code(self):
        code = InviteCode.objects.create(
            code="CASC123", user=self.pending_teacher, created_by=self.admin,
            expires_at=parse_datetime("2026-12-31T00:00:00Z"),
        )
        code_id = code.id
        self.pending_teacher.delete()
        self.assertFalse(InviteCode.objects.filter(id=code_id).exists())