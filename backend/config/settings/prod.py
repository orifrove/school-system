"""
Production settings.

Запускается через DJANGO_SETTINGS_MODULE=config.settings.prod
(задаётся в environment переменных production-сервера — см. docs/deployment.md,
будет создан в Phase 19).
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# ALLOWED_HOSTS в проде обязателен и без дефолта — намеренно не даём здесь
# fallback на пустой список, чтобы деплой с забытой переменной падал явно,
# а не тихо принимал любой Host-заголовок.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
