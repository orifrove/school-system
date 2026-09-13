from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Менеджер для custom User.

    User в этой системе не обязан иметь username/password —
    большинство пользователей (Teacher, Parent) аутентифицируются только
    через Telegram (telegram_id), без пароля вообще. `username`/`password`
    нужны только тем, кто заходит в Django Admin (в MVP — Admin).

    См. docs/django-apps.md, раздел 5, и docs/database.md — `username`
    не является частью согласованной бизнес-схемы БД, это чисто
    технический механизм для стандартной аутентификации Django Admin,
    добавленный на уровне реализации (не меняет одобренную схему).
    """

    use_in_migrations = True

    def _create_user(self, full_name, username=None, password=None, **extra_fields):
        if not full_name:
            raise ValueError("У пользователя обязательно должно быть full_name")

        user = self.model(full_name=full_name, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, full_name, username=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(full_name, username, password, **extra_fields)

    def create_superuser(self, full_name, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if not username:
            raise ValueError("Superuser обязательно должен иметь username (для входа в Django Admin)")

        return self._create_user(full_name, username, password, **extra_fields)
