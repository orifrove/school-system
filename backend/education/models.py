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