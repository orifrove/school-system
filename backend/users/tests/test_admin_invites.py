from datetime import timedelta

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import InviteCode, User


class InviteAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(full_name="Admin", username="admin", password="testpass")
        self.user = User.objects.create_user(full_name="Pending")
        self.client.force_login(self.admin_user)
        self.model_admin = admin.site._registry[InviteCode]
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.admin_user

    def data(self, expires=None):
        expires = expires or timezone.localtime(timezone.now() + timedelta(days=1))
        return {"code": "ADMIN-TEST", "user": self.user.pk, "status": "active",
                "expires_at_0": expires.strftime("%Y-%m-%d"), "expires_at_1": expires.strftime("%H:%M:%S")}

    def test_new_invite_has_random_code_and_future_expiry(self):
        first = self.model_admin.get_changeform_initial_data(self.request)
        second = self.model_admin.get_changeform_initial_data(self.request)
        self.assertNotEqual(first["code"], second["code"])
        self.assertGreaterEqual(len(first["code"]), 24)
        self.assertGreater(first["expires_at"], timezone.now() + timedelta(days=6))

    def test_admin_creates_invite_with_actual_issuer(self):
        data = self.data()
        data.update(created_by=self.user.pk, used_at="2020-01-01")
        response = self.client.post(reverse("admin:users_invitecode_add"), data)
        self.assertEqual(response.status_code, 302)
        invite = InviteCode.objects.get()
        self.assertEqual(invite.created_by, self.admin_user)
        self.assertIsNone(invite.used_at)

    def test_expired_active_invite_returns_form_error(self):
        response = self.client.post(reverse("admin:users_invitecode_add"), self.data(timezone.now() - timedelta(days=1)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "истекать в будущем")
        self.assertFalse(InviteCode.objects.exists())

    def test_linked_or_disabled_user_cannot_receive_active_invite(self):
        self.user.telegram_id = 123
        self.user.save()
        response = self.client.post(reverse("admin:users_invitecode_add"), self.data())
        self.assertContains(response, "без Telegram-привязки")
        self.user.telegram_id = None
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse("admin:users_invitecode_add"), self.data())
        self.assertContains(response, "без Telegram-привязки")
        self.assertFalse(InviteCode.objects.exists())

    def test_used_invite_cannot_be_reactivated_or_reassigned_by_post(self):
        invite = InviteCode.objects.create(code="USED", user=self.user, created_by=self.admin_user,
            status="used", used_at=timezone.now(), expires_at=timezone.now() - timedelta(days=1))
        response = self.client.post(reverse("admin:users_invitecode_change", args=[invite.pk]),
            {**self.data(), "code": "REPLACED", "user": self.admin_user.pk, "used_at": ""})
        self.assertEqual(response.status_code, 302)
        invite.refresh_from_db()
        self.assertEqual((invite.code, invite.user_id, invite.status), ("USED", self.user.pk, "used"))
        self.assertIsNotNone(invite.used_at)

    def test_active_code_can_be_invalidated_without_rewriting_identity(self):
        invite = InviteCode.objects.create(code="OLD", user=self.user, created_by=self.admin_user,
            expires_at=timezone.now() - timedelta(days=1))
        response = self.client.post(reverse("admin:users_invitecode_change", args=[invite.pk]),
            {**self.data(), "status": "invalidated"})
        self.assertEqual(response.status_code, 302)
        invite.refresh_from_db()
        self.assertEqual(invite.status, "invalidated")
        self.assertEqual(invite.code, "OLD")

    def test_nonstaff_cannot_issue_invites(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("admin:users_invitecode_add"), self.data())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertFalse(InviteCode.objects.exists())
