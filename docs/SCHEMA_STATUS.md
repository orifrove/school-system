# Schema Status — актуальное состояние на 2026-09-24

Все 17 моделей из первоначального проектирования (Phase 2) реализованы.
Этот файл — краткий актуальный снимок, не полная архитектурная документация
(она была потеряна при распаковке архива в начале Phase 3 и не восстановлена
полностью — решили держать актуальность здесь, а не в устаревших документах).

## Apps и модели

- users: User (custom), Role, UserRole
- education: Student, Subject, Group, Enrollment, Schedule, Lesson,
  Attendance, Grade, Question, Answer
- billing: BillingPeriod, Payment
- notifications: Notification

## Известные отличия от исходного Phase 2 проектирования

- Enrollment.group: on_delete изменён с SET_NULL на PROTECT.
  Причина: SET_NULL мог обнулить group_id у Enrollment, где
  subject/teacher уже NULL (групповой случай) - получалась строка
  со всеми тремя полями NULL, что нарушало CHECK-constraint
  enrollment_group_xor_individual. Обнаружено тестом, исправлено
  в коммите fix: change Enrollment.group on_delete to PROTECT.

## Не реализовано пока

- users.InviteCode - отложена, механизм безопасной привязки Telegram
  ещё не создан на уровне модели.
- Service layer / бизнес-правила, которые не выражаются DB constraint
  (Group.subject immutability, Enrollment overlap validation,
  Attendance eligibility, Grade-Lesson consistency) - Phase 4/5.

## Тесты

59/59 passing на момент последнего коммита (Phase 3.2.5).
