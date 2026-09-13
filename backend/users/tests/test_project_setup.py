from django.conf import settings
from django.test import TestCase


class ProjectSetupTests(TestCase):
    """
    Проверка, что базовая конфигурация проекта (Checkpoint 3.1) на месте —
    не тестирует бизнес-логику, только "проект вообще правильно настроен".
    """

    def test_custom_user_model_configured(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "users.User")

    def test_timezone_configured_correctly(self):
        # database.md, раздел 11: USE_TZ=True, Asia/Tashkent как business timezone.
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, "Asia/Tashkent")

    def test_local_apps_installed(self):
        for app in ("users", "education", "billing", "notifications"):
            self.assertIn(app, settings.INSTALLED_APPS)
