from django.conf import settings
from django.db import models
from django.db.models import Q


class Ward(models.Model):
    class Kind(models.TextChoices):
        GENERAL = "general", "General"
        ICU = "icu", "Intensive care"
        MATERNITY = "maternity", "Maternity"
        PEDIATRIC = "pediatric", "Pediatric"
        SURGICAL = "surgical", "Surgical"
        EMERGENCY = "emergency", "Emergency"

    name = models.CharField(max_length=80)
    code = models.CharField(max_length=8, unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.GENERAL)
    floor = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Bed(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        CLEANING = "cleaning", "Needs cleaning"
        RESERVED = "reserved", "Reserved"
        MAINTENANCE = "maintenance", "Out of service"

    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    label = models.CharField(max_length=12)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ward__code", "label"]
        constraints = [models.UniqueConstraint(fields=["ward", "label"], name="uniq_bed_label_per_ward")]

    def __str__(self):
        return f"{self.ward.code}-{self.label}"

    @property
    def current_admission(self):
        return self.admissions.filter(discharged_at__isnull=True).select_related("patient").first()


class Admission(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admissions")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="admissions")
    attending = models.ForeignKey("clinic.Doctor", null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="admissions")
    reason = models.CharField(max_length=200)
    admitted_at = models.DateTimeField(auto_now_add=True)
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharge_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-admitted_at"]
        constraints = [
            # A bed can hold only one current admission, and a patient can
            # only be admitted once at a time.
            models.UniqueConstraint(fields=["bed"], condition=Q(discharged_at__isnull=True),
                                    name="one_active_admission_per_bed"),
            models.UniqueConstraint(fields=["patient"], condition=Q(discharged_at__isnull=True),
                                    name="one_active_admission_per_patient"),
        ]

    def __str__(self):
        return f"{self.patient} in {self.bed}"
