from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Role, User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    fk_name = "user"
    extra = 0
    fields = ("role", "assigned_by", "assigned_at")
    readonly_fields = ("assigned_at",)


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
