from django.db import models


class Student(models.Model):
    """
    Ученик. НЕ является User — может вообще не иметь аккаунта в MVP
    (см. requirements.md, Phase 0, вопрос 1: Student Telegram access — V2).

    database.md, раздел 2 (модель Student).
    """

    user = models.OneToOneField(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_profile",
        help_text="V2: привязка Telegram-аккаунта напрямую к ученику. В MVP всегда NULL.",
    )
    full_name = models.CharField(max_length=255)
    birth_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_student"

    def __str__(self) -> str:
        return self.full_name


class Subject(models.Model):
    """
    Предмет (математика, английский и т.д.). database.md, раздел 2.
    Единственный источник истины для "какой это предмет" у Group —
    сама Group ссылается на Subject, не хранит название строкой.
    """

    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "education_subject"

    def __str__(self) -> str:
        return self.name


class Group(models.Model):
    """
    Учебная группа. database.md v4, раздел 2 (финальная схема после
    отказа от TeachingAssignment — см. Phase 2 review).

    Единственный источник истины "кто ведёт эту группу и по какому
    предмету" для группового обучения. teacher — обычное мутируемое
    поле: смена преподавателя это просто UPDATE, Group остаётся тем
    же объектом (database.md, раздел 5 — сценарий Teacher change).
    """

    subject = models.ForeignKey(
        "education.Subject",
        on_delete=models.PROTECT,
        related_name="groups",
    )
    teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="groups_teaching",
    )
    name = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_group"

    def __str__(self) -> str:
        return self.name


class Enrollment(models.Model):
    """
    Student записан на обучение — либо в составе Group, либо
    индивидуально. database.md v4, раздел 2.

    Ключевое архитектурное решение (Phase 2, финальный review):
    ровно одно из двух должно быть заполнено:
      - group  (групповое обучение — subject/teacher берутся из Group)
      - subject + teacher  (индивидуальное обучение — Group не создаётся)
    Это "дискриминированное объединение", проверяется CHECK-constraint
    ниже — не два независимых факта, а взаимоисключающий выбор.

    group: on_delete=PROTECT (не SET_NULL) — исправлено после того, как
    тест обнаружил конфликт: если бы Group удалялась физически, SET_NULL
    обнулил бы group_id у Enrollment, где subject/teacher тоже уже NULL
    (групповое обучение) — получилась бы строка, где ВСЕ три поля NULL,
    что нарушает CHECK-constraint enrollment_group_xor_individual.
    PROTECT предотвращает саму возможность такого состояния — Group
    физически нельзя удалить, пока на неё есть ссылки Enrollment
    (что соответствует database.md: Group в норме не удаляется,
    только деактивируется is_active=False).
    """

    student = models.ForeignKey(
        "education.Student",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    group = models.ForeignKey(
        "education.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="enrollments",
    )
    subject = models.ForeignKey(
        "education.Subject",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="individual_enrollments",
        help_text="Только для индивидуального обучения (group IS NULL).",
    )
    teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="individual_enrollments",
        help_text="Только для индивидуального обучения (group IS NULL).",
    )

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_ENDED, "Ended"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    price_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_enrollment"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(group__isnull=False, subject__isnull=True, teacher__isnull=True)
                    | models.Q(group__isnull=True, subject__isnull=False, teacher__isnull=False)
                ),
                name="enrollment_group_xor_individual",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.group or self.subject}"




class Schedule(models.Model):
    """
    Шаблон повторяющегося расписания. database.md v4, раздел 2/5.

    Та же логика дискриминированного объединения, что у Enrollment:
    ровно один из двух источников — Group (групповое расписание)
    или Enrollment (индивидуальное, и тогда это тот самый Enrollment
    с group=None — расписание одного конкретного ученика).

    Хранит ЛОКАЛЬНОЕ время центра (weekday + time, без даты и без TZ) —
    это шаблон "каждую среду в 15:00", а не конкретный момент.
    Конкретные datetime появляются только у Lesson.
    """

    group = models.ForeignKey(
        "education.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedules",
    )
    enrollment = models.ForeignKey(
        "education.Enrollment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedules",
    )

    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=64, null=True, blank=True)

    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_schedule"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(group__isnull=False, enrollment__isnull=True)
                    | models.Q(group__isnull=True, enrollment__isnull=False)
                ),
                name="schedule_group_xor_enrollment",
            ),
        ]

    def __str__(self) -> str:
        target = self.group or self.enrollment
        return f"{target} — {self.get_weekday_display()} {self.start_time}"




class Lesson(models.Model):
    """
    Конкретное занятие на конкретную дату/время, сгенерированное из
    Schedule. database.md v4, раздел 5.

    teacher/subject ДЕНОРМАЛИЗОВАНЫ — намеренно, единственное место
    в схеме с осознанным дублированием (не ошибка, как было с
    TeachingAssignment). Это исторический snapshot: если Group.teacher
    сменится позже, прошлые Lesson должны сохранить того учителя,
    который реально провёл занятие, а не "утекать" на нового.

    starts_at/ends_at — полноценный timezone-aware datetime (UTC в БД),
    не date+time, как в Schedule — тут это уже конкретный момент
    времени, а не шаблон (database.md, раздел 5, разбор starts_at vs
    date+time).
    """

    schedule = models.ForeignKey(
        "education.Schedule",
        on_delete=models.PROTECT,
        related_name="lessons",
    )
    teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="lessons_taught",
        help_text="Денормализовано — снимок на момент создания занятия.",
    )
    subject = models.ForeignKey(
        "education.Subject",
        on_delete=models.PROTECT,
        related_name="lessons",
        help_text="Денормализовано — снимок на момент создания занятия.",
    )

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    room = models.CharField(max_length=64, null=True, blank=True)

    STATUS_PLANNED = "planned"
    STATUS_HELD = "held"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_HELD, "Held"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    cancelled_reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_lesson"
        constraints = [
            models.UniqueConstraint(fields=["schedule", "starts_at"], name="uniq_lesson_schedule_starts_at"),
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="lesson_ends_after_starts"),
        ]

    def __str__(self) -> str:
        return f"{self.subject} — {self.starts_at:%Y-%m-%d %H:%M}"





class Attendance(models.Model):
    """
    Отметка посещаемости Student на конкретном Lesson. database.md v4,
    раздел 13. Работает ОДИНАКОВО для группового и индивидуального
    занятия — не знает и не должен знать про Group/Enrollment вообще,
    только про Lesson и Student напрямую (в этом и был смысл решения
    из Phase 2: развилка group/individual сосредоточена в Schedule,
    Attendance её не касается).
    """

    lesson = models.ForeignKey(
        "education.Lesson",
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    student = models.ForeignKey(
        "education.Student",
        on_delete=models.PROTECT,
        related_name="attendances",
    )

    STATUS_PRESENT = "present"
    STATUS_ABSENT = "absent"
    STATUS_LATE = "late"
    STATUS_EXCUSED = "excused"
    STATUS_CHOICES = [
        (STATUS_PRESENT, "Present"),
        (STATUS_ABSENT, "Absent"),
        (STATUS_LATE, "Late"),
        (STATUS_EXCUSED, "Excused"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    comment = models.CharField(max_length=255, null=True, blank=True)

    marked_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendances_marked",
    )
    marked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "education_attendance"
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="uniq_attendance_lesson_student"),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.lesson} — {self.status}"




class Grade(models.Model):
    """
    Оценка Student. database.md v4, раздел 3.

    Ссылается на Enrollment, НЕ на отдельные student+subject+teacher —
    так однозначно определяется, к какому именно периоду обучения
    относится оценка (даже если ученик повторно учился тому же
    предмету у другого учителя — это будет другой Enrollment).

    value — строка, не число: шкала оценивания (5/10/100-балльная,
    буквенная) ещё не подтверждена владельцем центра (requirements.md,
    Phase 0, вопрос 5) — GradingScale как отдельная сущность
    сознательно отложена в V2 (database.md, раздел 18).
    """

    enrollment = models.ForeignKey(
        "education.Enrollment",
        on_delete=models.PROTECT,
        related_name="grades",
    )
    lesson = models.ForeignKey(
        "education.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grades",
        help_text="NULL — если оценка не привязана к конкретному занятию (например, итоговая).",
    )
    given_by_teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="grades_given",
        help_text="Исторический snapshot — кто РЕАЛЬНО поставил оценку, "
                  "независимо от того, кто сейчас Group.teacher.",
    )

    value = models.CharField(max_length=16)
    max_value = models.CharField(max_length=16, null=True, blank=True)
    comment = models.CharField(max_length=255, null=True, blank=True)
    given_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "education_grade"

    def __str__(self) -> str:
        return f"{self.enrollment} — {self.value}"