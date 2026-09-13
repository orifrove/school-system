"""
Base Django settings — shared between dev and prod.

Все секреты и окружение-специфичные значения читаются из переменных
окружения (см. .env.example в корне backend/). Ничего чувствительного
не хардкодится здесь и не попадает в Git.
"""

from pathlib import Path

import environ

# backend/config/settings/base.py -> нужно подняться на 3 уровня до backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# .env лежит в backend/.env — читаем его, если файл существует
# (в проде переменные обычно приходят из окружения контейнера напрямую,
# .env-файла может не быть — это нормально, django-environ не упадёт).
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # локальные apps проекта (см. docs/django-apps.md)
    "users",
    "education",
    "billing",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---------------------------------------------------------
# Учебный центр в Узбекистане, PostgreSQL — источник истины (architecture.md).
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# --- Custom user model --------------------------------------------------
# ОБЯЗАТЕЛЬНО задано до первой миграции (docs/django-apps.md, раздел 5).
AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization / Timezone ------------------------------------
# database.md, раздел 11 (Timezone strategy): USE_TZ=True, хранение в UTC,
# Asia/Tashkent — бизнес/display timezone учебного центра.
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Logging -------------------------------------------------------------
# Базовый logging на этом этапе (Phase 3): вывод в консоль, читаемый формат.
# Расширим (файлы, ротация, уровни по приложениям) при необходимости
# в более поздних фазах — не усложняем раньше времени (правило проекта).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}
