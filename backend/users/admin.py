from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone
from datetime import timedelta
import secrets

from .models import InviteCode, Role, User, UserRole
from .forms import InviteCodeAdminForm


class UserRoleInline(admin.TabularInline):
    model = UserRole
    fk_name = "user"
    extra = 0
    fields = ("role", "assigned_by", "assigned_at")
    readonly_fields = ("assigned_at",)
    autocomplete_fields = ("role", "assigned_by")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Не наследуем поля username/password wizard из стандартного UserAdmin
    # один в один — у нас другой набор обязательных полей (full_name, а не
    # first_name/last_name), поэтому переопределяем явно.
    model = User
    list_display = ("id", "full_name", "username", "telegram_id", "phone", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff")
    search_fields = ("full_name", "username", "phone", "telegram_id")
    ordering = ("id",)
    inlines = [UserRoleInline]

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Личные данные", {"fields": ("full_name", "phone", "telegram_id")}),
        ("Права доступа", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "full_name", "password1", "password2", "is_staff", "is_active"),
        }),
    )
    readonly_fields = ("last_login", "created_at", "updated_at")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("id", "code")
    search_fields = ("code",)


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "assigned_by", "assigned_at")
    list_filter = ("role",)
    autocomplete_fields = ("user", "role", "assigned_by")





@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    form = InviteCodeAdminForm
    list_display = ("id", "code", "user", "status", "is_expired", "created_by", "expires_at", "used_at")
    list_filter = ("status",)
    search_fields = ("code", "user__full_name")
    autocomplete_fields = ("user",)
    list_select_related = ("user", "created_by")
    readonly_fields = ("created_at", "created_by", "used_at")
    ordering = ("-created_at", "-pk")
    list_per_page = 30

    @admin.display(boolean=True, description="Срок истёк")
    def is_expired(self, obj):
        return obj.expires_at <= timezone.now()

    def get_changeform_initial_data(self, request):
        data = super().get_changeform_initial_data(request)
        data.setdefault("code", secrets.token_urlsafe(24))
        data.setdefault("expires_at", timezone.localtime(timezone.now() + timedelta(days=7)))
        return data

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj is not None:
            fields.extend(("code", "user"))
            if obj.status != InviteCode.STATUS_ACTIVE or obj.used_at is not None:
                fields.extend(("status", "expires_at"))
        return tuple(fields)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
