import secrets
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


NO_ALLERGY_WORDS = {"none", "nil", "no", "n/a", "na", "nkda", "no known allergies"}


def _split(text):
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


class HealthProfile(models.Model):
    """The patient's "health passport": the facts every clinician should see
    before a visit."""

    class Sex(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other / prefer not to say"

    BLOOD_GROUPS = [(g, g) for g in ("A+", "A−", "B+", "B−", "AB+", "AB−", "O+", "O−")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="health")
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=8, choices=Sex.choices, blank=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, blank=True)
    height_cm = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(250)]
    )
    allergies = models.TextField(blank=True, help_text="Comma separated, e.g. penicillin, peanuts")
    chronic_conditions = models.TextField(blank=True, help_text="Comma separated")
    current_medications = models.TextField(blank=True, help_text="Comma separated")
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    COMPLETENESS_FIELDS = (
        "date_of_birth", "sex", "blood_group", "height_cm",
        "emergency_contact_name", "emergency_contact_phone",
    )

    def __str__(self):
        return f"Health profile of {self.user}"

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def allergy_list(self):
        return _split(self.allergies)

    @property
    def known_allergies(self):
        """Allergies excluding explicit "none" answers."""
        return [a for a in self.allergy_list if a.lower() not in NO_ALLERGY_WORDS]

    @property
    def condition_list(self):
        return _split(self.chronic_conditions)

    @property
    def medication_list(self):
        return _split(self.current_medications)

    @property
    def completeness(self):
        """Percent of the passport filled in. Allergies count as filled only
        when explicitly answered (\"none\" is a valid answer)."""
        filled = sum(1 for f in self.COMPLETENESS_FIELDS if getattr(self, f))
        filled += 1 if self.allergies.strip() else 0
        return round(100 * filled / (len(self.COMPLETENESS_FIELDS) + 1))

    def allergy_conflicts(self, medicine_names):
        """Return (medicine, allergy) pairs where a prescribed medicine name
        mentions a recorded allergy. Simple, transparent string matching —
        a safety net, not a substitute for clinical judgement."""
        conflicts = []
        allergies = [a.lower() for a in self.known_allergies]
        for med in medicine_names:
            m = med.lower()
            for allergy in allergies:
                if allergy and (allergy in m or m in allergy):
                    conflicts.append((med, allergy))
        return conflicts


class VitalReading(models.Model):
    """One set of vitals. Every metric is optional so patients can log just
    what they measured."""

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vitals")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    systolic = models.PositiveSmallIntegerField("Systolic (mmHg)", null=True, blank=True,
                                                validators=[MinValueValidator(50), MaxValueValidator(260)])
    diastolic = models.PositiveSmallIntegerField("Diastolic (mmHg)", null=True, blank=True,
                                                 validators=[MinValueValidator(30), MaxValueValidator(160)])
    heart_rate = models.PositiveSmallIntegerField("Heart rate (bpm)", null=True, blank=True,
                                                  validators=[MinValueValidator(20), MaxValueValidator(250)])
    glucose = models.DecimalField("Blood glucose (mg/dL)", max_digits=5, decimal_places=1, null=True, blank=True,
                                  validators=[MinValueValidator(Decimal("20")), MaxValueValidator(Decimal("700"))])
    temperature = models.DecimalField("Temperature (°C)", max_digits=4, decimal_places=1, null=True, blank=True,
                                      validators=[MinValueValidator(Decimal("30")), MaxValueValidator(Decimal("45"))])
    spo2 = models.PositiveSmallIntegerField("SpO₂ (%)", null=True, blank=True,
                                            validators=[MinValueValidator(50), MaxValueValidator(100)])
    weight_kg = models.DecimalField("Weight (kg)", max_digits=5, decimal_places=1, null=True, blank=True,
                                    validators=[MinValueValidator(Decimal("1")), MaxValueValidator(Decimal("400"))])
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["patient", "-recorded_at"])]

    def __str__(self):
        return f"Vitals for {self.patient} at {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def blood_pressure(self):
        if self.systolic and self.diastolic:
            return f"{self.systolic}/{self.diastolic}"
        return ""

    def flags(self):
        """Out-of-range readings as (label, level, message). Levels: 'high',
        'low', 'critical'. Thresholds are general adult reference ranges."""
        out = []
        if self.systolic and self.diastolic:
            if self.systolic >= 180 or self.diastolic >= 120:
                out.append(("Blood pressure", "critical", "Hypertensive crisis range"))
            elif self.systolic >= 140 or self.diastolic >= 90:
                out.append(("Blood pressure", "high", "High (stage 2)"))
            elif self.systolic >= 130 or self.diastolic >= 80:
                out.append(("Blood pressure", "high", "Elevated (stage 1)"))
            elif self.systolic < 90 or self.diastolic < 60:
                out.append(("Blood pressure", "low", "Low"))
        if self.heart_rate:
            if self.heart_rate > 120 or self.heart_rate < 45:
                out.append(("Heart rate", "critical", f"{self.heart_rate} bpm"))
            elif self.heart_rate > 100:
                out.append(("Heart rate", "high", "Above resting range"))
            elif self.heart_rate < 60:
                out.append(("Heart rate", "low", "Below resting range"))
        if self.glucose:
            if self.glucose >= 250 or self.glucose < 54:
                out.append(("Glucose", "critical", f"{self.glucose} mg/dL"))
            elif self.glucose >= 180:
                out.append(("Glucose", "high", "High"))
            elif self.glucose < 70:
                out.append(("Glucose", "low", "Low"))
        if self.spo2:
            if self.spo2 < 90:
                out.append(("SpO₂", "critical", f"{self.spo2}%"))
            elif self.spo2 < 95:
                out.append(("SpO₂", "low", "Below normal"))
        if self.temperature:
            if self.temperature >= Decimal("39.5"):
                out.append(("Temperature", "critical", "High fever"))
            elif self.temperature >= Decimal("38"):
                out.append(("Temperature", "high", "Fever"))
            elif self.temperature < Decimal("35.5"):
                out.append(("Temperature", "low", "Low"))
        return out


def _verification_code():
    return secrets.token_hex(5).upper()


class Consultation(models.Model):
    """Visit note + e-prescription written by the doctor at the end of an
    appointment."""

    appointment = models.OneToOneField("appointments.Appointment", on_delete=models.CASCADE,
                                       related_name="consultation")
    diagnosis = models.CharField(max_length=200)
    clinical_notes = models.TextField(blank=True)
    advice = models.TextField("Advice for the patient", blank=True)
    follow_up_in_days = models.PositiveSmallIntegerField(null=True, blank=True)
    allergy_override = models.BooleanField(default=False, help_text="Doctor confirmed despite an allergy warning")
    verification_code = models.CharField(max_length=12, unique=True, default=_verification_code, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consultation {self.appointment.code}: {self.diagnosis}"

    def get_absolute_url(self):
        return reverse("records:prescription", args=[self.appointment.code])

    @property
    def verify_url(self):
        return settings.SITE_URL + reverse("records:verify", args=[self.verification_code])

    @property
    def follow_up_date(self):
        if self.follow_up_in_days:
            return (self.created_at + timedelta(days=self.follow_up_in_days)).date()
        return None


class PrescriptionItem(models.Model):
    consultation = models.ForeignKey(Consultation, on_delete=models.CASCADE, related_name="items")
    medicine = models.CharField(max_length=120)
    dosage = models.CharField(max_length=60, help_text="e.g. 500 mg")
    frequency = models.CharField(max_length=60, help_text="e.g. 1-0-1 after meals")
    duration = models.CharField(max_length=60, help_text="e.g. 5 days")
    instructions = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.medicine} {self.dosage}"


class AccessLog(models.Model):
    """Who looked at or changed a patient's record. Patients can see this
    themselves on their Privacy page."""

    class Action(models.TextChoices):
        VIEW_CHART = "view_chart", "Viewed health record"
        CONSULT = "consult", "Opened consultation"
        PRESCRIBE = "prescribe", "Issued prescription"
        RECORD_VITALS = "vitals", "Recorded vitals"
        ADMIT = "admit", "Admitted to ward"

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=16, choices=Action.choices)
    detail = models.CharField(max_length=200, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self):
        return f"{self.actor} {self.get_action_display()} ({self.patient})"

    @classmethod
    def record(cls, request, patient, action, detail=""):
        if request.user == patient:
            return None
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        return cls.objects.create(patient=patient, actor=request.user, action=action, detail=detail[:200],
                                  ip_address=ip or None)
