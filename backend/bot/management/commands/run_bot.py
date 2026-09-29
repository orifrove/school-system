from django.core.management.base import BaseCommand

from bot.main import main


class Command(BaseCommand):
    help = "Запускает Telegram-бота (polling режим для разработки)."

    def handle(self, *args, **options):
        main()