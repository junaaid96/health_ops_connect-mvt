from django.contrib import admin

from .models import Admission, Bed, Ward


class BedInline(admin.TabularInline):
    model = Bed
    extra = 0


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "floor")
    inlines = [BedInline]


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("patient", "bed", "attending", "admitted_at", "discharged_at")
    list_filter = ("discharged_at",)
