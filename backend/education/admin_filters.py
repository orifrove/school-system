from datetime import datetime, time, timedelta

from django.contrib import admin
from django.utils import timezone

from education.models import Lesson


class LessonPeriodFilter(admin.SimpleListFilter):
    title = "Период занятий"
    parameter_name = "lesson_period"

    def lookups(self, request, model_admin):
        return (
            ("today", "Сегодня"),
            ("tomorrow", "Завтра"),
            ("week", "Ближайшие 7 дней"),
            ("overdue", "Просроченные запланированные"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"today", "tomorrow", "week", "overdue"}:
            return queryset
        now = timezone.now()
        if value == "overdue":
            return queryset.filter(status=Lesson.STATUS_PLANNED, ends_at__lte=now)
        zone = timezone.get_default_timezone()
        today = timezone.localdate(now, timezone=zone)
        first = today + timedelta(days=1) if value == "tomorrow" else today
        last = first + timedelta(days=7 if value == "week" else 1)
        start = timezone.make_aware(datetime.combine(first, time.min), zone)
        end = timezone.make_aware(datetime.combine(last, time.min), zone)
        return queryset.filter(starts_at__gte=start, starts_at__lt=end)
