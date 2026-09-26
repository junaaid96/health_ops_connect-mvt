from django.contrib import admin

from .models import Doctor, Review, Specialty, TimeOff, WeeklyAvailability


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "icon")
    prepopulated_fields = {"slug": ("name",)}


class AvailabilityInline(admin.TabularInline):
    model = WeeklyAvailability
    extra = 0


class TimeOffInline(admin.TabularInline):
    model = TimeOff
    extra = 0


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("__str__", "specialty", "fee", "is_verified", "offers_video", "offers_in_person")
    list_filter = ("is_verified", "specialty", "offers_video")
    search_fields = ("user__first_name", "user__last_name", "user__email", "license_number")
    list_editable = ("is_verified",)
    inlines = [AvailabilityInline, TimeOffInline]
    raw_id_fields = ("user",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("doctor", "patient", "rating", "created_at")
    list_filter = ("rating",)
