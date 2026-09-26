from django.contrib import admin

from .models import Appointment, WaitlistEntry


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("code", "patient", "doctor", "scheduled_at", "mode", "status", "urgency", "payment_status")
    list_filter = ("status", "mode", "urgency", "payment_status", "doctor__specialty")
    search_fields = ("code", "patient__email", "patient__first_name", "patient__last_name", "reason")
    date_hierarchy = "scheduled_at"
    raw_id_fields = ("patient", "doctor", "cancelled_by")
    readonly_fields = ("code", "created_at", "updated_at")


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "date", "notified_at")
