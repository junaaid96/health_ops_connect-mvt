from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Notification, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "email_verified", "is_active")
    list_filter = ("role", "email_verified", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "phone")
    fieldsets = BaseUserAdmin.fieldsets + (("HealthOPS", {"fields": ("role", "phone", "avatar", "email_verified")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("HealthOPS", {"fields": ("email", "role")}),)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read")
    search_fields = ("title", "user__email")
