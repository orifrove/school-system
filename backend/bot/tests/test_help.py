from asgiref.sync import async_to_sync
from django.test import TestCase

from bot.handlers.common import help_text
from users.models import Role, User, UserRole


class HelpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(full_name="User")

    def test_anonymous_help_explains_invitation(self):
        text = async_to_sync(help_text)(None)
        self.assertIn("код приглашения", text)
        self.assertNotIn("/groups", text)

    def test_parent_help_only_shows_parent_commands(self):
        UserRole.objects.create(user=self.user, role=Role.objects.create(code=Role.PARENT))
        text = async_to_sync(help_text)(self.user.pk)
        self.assertIn("/children", text)
        self.assertNotIn("/questions", text)
        self.assertNotIn("/groups", text)

    def test_teacher_help_only_shows_teacher_commands(self):
        UserRole.objects.create(user=self.user, role=Role.objects.create(code=Role.TEACHER))
        text = async_to_sync(help_text)(self.user.pk)
        self.assertIn("/groups", text)
        self.assertIn("/questions", text)
        self.assertNotIn("/children", text)

    def test_multi_role_help_covers_both_roles_and_revocation(self):
        for code in [Role.TEACHER, Role.PARENT]:
            UserRole.objects.create(user=self.user, role=Role.objects.create(code=code))
        text = async_to_sync(help_text)(self.user.pk)
        self.assertIn("/groups", text)
        self.assertIn("/children", text)
        self.assertLess(len(text), 4096)
        self.user.is_active = False
        self.user.save()
        text = async_to_sync(help_text)(self.user.pk)
        self.assertNotIn("/groups", text)
        self.assertNotIn("/children", text)

    def test_no_roles_help_explains_missing_access(self):
        self.assertIn("Обратитесь к администратору", async_to_sync(help_text)(self.user.pk))
