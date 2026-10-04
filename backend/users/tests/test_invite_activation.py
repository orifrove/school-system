from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from users.models import InviteCode, User
from users.services import activate_invite_code


class InviteActivationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(full_name="Admin")
        self.user = User.objects.create_user(full_name="Teacher")
        self.invite = InviteCode.objects.create(
            code="TEST", user=self.user, created_by=self.admin,
            expires_at=timezone.now() + timedelta(days=1),
        )

    def test_success_and_replay(self):
        self.assertEqual(activate_invite_code("TEST", 123), "ok")
        self.user.refresh_from_db()
        self.invite.refresh_from_db()
        self.assertEqual(self.user.telegram_id, 123)
        self.assertEqual(self.invite.status, "used")
        self.assertIsNotNone(self.invite.used_at)
        self.assertEqual(activate_invite_code("TEST", 456), "used")
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_id, 123)

    def test_expiry_including_exact_boundary(self):
        now = timezone.now()
        self.invite.expires_at = now
        self.invite.save()
        with patch("users.services.timezone.now", return_value=now):
            self.assertEqual(activate_invite_code("TEST", 123), "expired")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.telegram_id)

    def test_invalidated_and_missing_codes(self):
        self.invite.status = "invalidated"
        self.invite.save()
        for code in ["TEST", "missing", "", "X" * 65]:
            self.assertEqual(activate_invite_code(code, 123), "not_found")

    def test_disabled_user(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(activate_invite_code("TEST", 123), "inactive")

    def test_existing_target_link_is_preserved(self):
        self.user.telegram_id = 999
        self.user.save()
        self.assertEqual(activate_invite_code("TEST", 123), "already_linked")
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_id, 999)

    def test_telegram_cannot_claim_second_user(self):
        User.objects.create_user(full_name="Existing", telegram_id=123)
        self.assertEqual(activate_invite_code("TEST", 123), "already_linked")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.telegram_id)

    def test_inconsistent_used_timestamp_is_not_reusable(self):
        self.invite.used_at = timezone.now()
        self.invite.save()
        self.assertEqual(activate_invite_code("TEST", 123), "used")

    def test_failed_invite_save_rolls_back_user_link(self):
        with patch.object(InviteCode, "save", side_effect=RuntimeError("save failed")):
            with self.assertRaises(RuntimeError):
                activate_invite_code("TEST", 123)
        self.user.refresh_from_db()
        self.invite.refresh_from_db()
        self.assertIsNone(self.user.telegram_id)
        self.assertEqual(self.invite.status, "active")


class ConcurrentInviteActivationTests(TransactionTestCase):
    def test_only_one_caller_can_consume_invite(self):
        admin = User.objects.create_user(full_name="Admin")
        user = User.objects.create_user(full_name="Teacher")
        InviteCode.objects.create(code="RACE", user=user, created_by=admin,
                                  expires_at=timezone.now() + timedelta(days=1))
        barrier = Barrier(2)

        def activate(telegram_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return activate_invite_code("RACE", telegram_id)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(activate, [101, 102]))
        self.assertCountEqual(results, ["ok", "used"])
        user.refresh_from_db()
        self.assertIn(user.telegram_id, [101, 102])

    def test_two_invites_cannot_claim_same_telegram(self):
        admin = User.objects.create_user(full_name="Admin")
        for code in ["FIRST", "SECOND"]:
            user = User.objects.create_user(full_name=code)
            InviteCode.objects.create(code=code, user=user, created_by=admin,
                                      expires_at=timezone.now() + timedelta(days=1))
        barrier = Barrier(2)

        def activate(code):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return activate_invite_code(code, 103)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(activate, ["FIRST", "SECOND"]))
        self.assertCountEqual(results, ["ok", "already_linked"])
        self.assertEqual(User.objects.filter(telegram_id=103).count(), 1)
        self.assertEqual(InviteCode.objects.filter(status="used").count(), 1)
