# Система управления учебным центром

Django, PostgreSQL и Telegram-бот для преподавателей и родителей.

## Команды в Windows PowerShell

Из корня проекта `C:\Users\hp\Desktop\school system`:

```powershell
.\manage.ps1 check
.\manage.ps1 run_bot
```

Скрипт сам использует `backend\venv\Scripts\python.exe` и запускает Django
из `backend`. Активация окружения не требуется. Бот работает до Ctrl+C;
перед повторным запуском остановите прежний процесс.

Проверка уведомлений без отправки:

```powershell
.\manage.ps1 check_parent_notifications --student-id 4
.\manage.ps1 dispatch_notifications --summary-only
.\manage.ps1 dispatch_notifications --limit 10
```

Замените 4 на ID нужного ученика. Предпросмотр не создаёт события:
для новых уведомлений нужен настроенный родитель и новое действие преподавателя.

Из папки `backend` используйте `..\manage.ps1 check`. Из любой другой папки:

```powershell
& "C:\Users\hp\Desktop\school system\manage.ps1" check
```

Существующий способ запуска из `backend` также работает:

```powershell
.\venv\Scripts\python.exe manage.py check
```

Скрипт требует уже настроенные `backend\venv`, зависимости и PostgreSQL.
Он не устанавливает пакеты и не меняет конфигурацию. Ошибки Django передаются
в консоль и через `$LASTEXITCODE`. Рабочая папка возвращается к исходной.

## Инструкции

- [Работа с ботом](docs/BOT_OPERATIONS.md)
- [Django Admin](docs/ADMIN_WORKFLOWS.md)
- [Родительские оплаты](docs/PARENT_BILLING.md)
- [Уведомления и диагностика](docs/NOTIFICATIONS.md)
- [Состояние реализации](docs/SCHEMA_STATUS.md)
