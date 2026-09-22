from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "event_type", "channel", "status", "created_at", "sent_at")
    list_filter = ("status", "channel", "event_type")
    search_fields = ("recipient__full_name", "event_type")
    autocomplete_fields = ("recipient",)
    readonly_fields = ("created_at",)