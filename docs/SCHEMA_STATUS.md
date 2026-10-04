# Schema Status — актуальное состояние на 2026-10-04

Реализованы 18 моделей. Этот файл — краткий снимок состояния кода;
он не заменяет подробную архитектурную документацию.

## Apps и модели

- users: User (custom), Role, UserRole, InviteCode.
- education: Student, Subject, Group, Enrollment, Schedule, Lesson,
  Attendance, Grade, Question, Answer, ParentStudent.
- billing: BillingPeriod, Payment.
- notifications: Notification.

## Основные решения

- Enrollment задаёт либо Group, либо Subject + Teacher; сочетание
  контролируется CHECK-constraint. Enrollment.group использует PROTECT:
  SET_NULL нарушал бы constraint для группового обучения.
- Schedule задаёт либо Group, либо Enrollment; обе связи используют PROTECT.
- Lesson.teacher и Lesson.subject сохраняют исторический snapshot.
  Grade.given_by_teacher сохраняет автора оценки.
- BillingPeriod.amount_due — snapshot суммы начисления.
- Notification имеет уникальность по recipient + event_key.
- InviteCode обеспечивает одноразовую привязку Telegram к созданному User.
  У пользователя может быть не более одного active-кода.
  Поле code имеет unique=True; избыточный db_index=True удалён
  миграцией users.0004_alter_invitecode_code.

## Service layer и доступ

В education/services.py реализованы update_group, change_group_teacher,
mark_attendance, create_enrollment и add_grade: защита предмета группы
с учебной историей, обновление учителя planned-занятий, проверка допуска
и upsert посещаемости, проверка пересечений Enrollment и согласованности
Grade с Lesson.

В education/authorization.py реализованы проверки конкретных связей
учителя с обучением и родителя с учеником через ParentStudent.

## Telegram Bot — Phase 6.1

Реализованы запуск через python manage.py run_bot, polling для разработки,
auth middleware, /start и обработка invite-кода. Приложение bot включено
в INSTALLED_APPS.

По результатам ранее выполненной ручной проверки бот отвечает в Telegram,
/start работает, неверный и истёкший коды отклоняются. Успешную активацию
и повторный /start ещё требуется подтвердить вручную после исправления
expires_at у тестового кода в dev-БД.

## Что осталось

- Teacher/Parent/Admin handlers; следующий этап — Phase 6.2: Teacher handlers.
- Отправка уведомлений (модель Notification уже существует).
- Admin Web Panel, handlers платежей и сообщений.
- Автоматические тесты bot handlers и последующие интеграционные проверки.

## Проверки

2026-10-04: python manage.py check — без ошибок; makemigrations --check --dry-run — без изменений; python manage.py test --noinput — 81/81 passing на PostgreSQL. Проверки выполнены отдельным Python 3.13.7 с зависимостями backend/venv; пользовательский venv не изменялся. Миграция users.0004 применена в dev-БД; sqlmigrate показывает no-op.
