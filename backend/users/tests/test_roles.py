from django.db import IntegrityError, transaction
from django.test import TestCase

from users.models import Role, User, UserRole


class RoleModelTests(TestCase):
    def test_create_role(self):
        role = Role.objects.create(code=Role.TEACHER)
        self.assertEqual(str(role), role.get_code_display())

    def test_role_code_uniqueness(self):
        Role.objects.create(code=Role.ADMIN)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Role.objects.create(code=Role.ADMIN)


class UserRoleModelTests(TestCase):
    def setUp(self):
        self.admin_role = Role.objects.create(code=Role.ADMIN)
        self.teacher_role = Role.objects.create(code=Role.TEACHER)
        self.parent_role = Role.objects.create(code=Role.PARENT)
        self.super_admin = User.objects.create_superuser(
            full_name="Главный админ", username="root", password="root-pass-123"
        )

    def test_assign_single_role(self):
        teacher = User.objects.create_user(full_name="Учитель Иванов")
        UserRole.objects.create(user=teacher, role=self.teacher_role, assigned_by=self.super_admin)

        self.assertEqual(teacher.user_roles.count(), 1)
        self.assertEqual(teacher.user_roles.first().role, self.teacher_role)

    def test_teacher_plus_admin_multiple_roles(self):
        """
        Ключевой сценарий из requirements.md: одна учительница = Teacher + Admin
        одновременно. Система должна допускать это без конфликтов.
        """
        person = User.objects.create_user(full_name="Учительница математики")

        UserRole.objects.create(user=person, role=self.teacher_role, assigned_by=self.super_admin)
        UserRole.objects.create(user=person, role=self.admin_role, assigned_by=self.super_admin)

        role_codes = set(person.user_roles.values_list("role__code", flat=True))
        self.assertEqual(role_codes, {Role.TEACHER, Role.ADMIN})

    def test_cannot_assign_same_role_twice(self):
        """UNIQUE(user, role) — нельзя назначить одну роль дважды."""
        person = User.objects.create_user(full_name="Родитель Петров")
        UserRole.objects.create(user=person, role=self.parent_role, assigned_by=self.super_admin)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRole.objects.create(user=person, role=self.parent_role, assigned_by=self.super_admin)

    def test_role_cannot_be_deleted_while_in_use(self):
        """
        PROTECT на UserRole.role — раздел 14 database.md: справочники
        защищены от удаления, если на них есть ссылки.
        """
        person = User.objects.create_user(full_name="Родитель Сидоров")
        UserRole.objects.create(user=person, role=self.parent_role, assigned_by=self.super_admin)

        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            self.parent_role.delete()

    def test_assigned_by_set_null_when_admin_deleted(self):
        """SET_NULL на assigned_by — не критично, если назначивший админ удалён."""
        person = User.objects.create_user(full_name="Учитель Ким")
        user_role = UserRole.objects.create(
            user=person, role=self.teacher_role, assigned_by=self.super_admin
        )

        self.super_admin.delete()
        user_role.refresh_from_db()
        self.assertIsNone(user_role.assigned_by)
