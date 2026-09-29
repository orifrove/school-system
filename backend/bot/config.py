"""
Настройки бота. Читаются из тех же переменных окружения, что и Django
(один .env на весь backend, как договаривались в architecture.md
раздел 1 — бот и Django живут в одном процессе/репозитории).
"""

import environ

env = environ.Env()

BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")