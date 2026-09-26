from django.contrib import admin

from .models import AccessLog, Consultation, HealthProfile, PrescriptionItem, VitalReading


@admin.register(HealthProfile)
class HealthProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "blood_group", "date_of_birth", "updated_at")
    search_fields = ("user__email", "user__first_name", "user__last_name")


@admin.register(VitalReading)
class VitalReadingAdmin(admin.ModelAdmin):
    list_display = ("patient", "recorded_at", "blood_pressure", "heart_rate", "glucose", "spo2")


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ("appointment", "diagnosis", "verification_code", "created_at")
    search_fields = ("appointment__code", "diagnosis", "verification_code")
    inlines = [PrescriptionItemInline]


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "patient", "action", "ip_address")
    list_filter = ("action",)

    def has_change_permission(self, request, obj=None):
        return False  # audit trail is append-only
