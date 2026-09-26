from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.functional import cached_property


class User(AbstractUser):
    """A single user model for every role; role-specific data lives in
    related profiles (`clinic.Doctor`, `records.HealthProfile`)."""

    class Role(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        STAFF = "staff", "Hospital staff"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.PATIENT, db_index=True)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    email_verified = models.BooleanField(default=False)

    @property
    def is_patient(self):
        return self.role == self.Role.PATIENT

    @property
    def is_doctor(self):
        return self.role == self.Role.DOCTOR and hasattr(self, "doctor")

    @property
    def is_ops(self):
        """Front desk / operations staff (superusers count too)."""
        return self.role == self.Role.STAFF or self.is_superuser

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        if self.role == self.Role.DOCTOR and full:
            return f"Dr. {full}"
        return full or self.username

    @property
    def initials(self):
        parts = [p for p in (self.first_name, self.last_name) if p]
        if not parts:
            return self.username[:2].upper()
        return "".join(p[0] for p in parts[:2]).upper()

    @cached_property
    def avatar_url(self):
        if self.role == self.Role.DOCTOR and hasattr(self, "doctor") and self.doctor.photo:
            return self.doctor.photo.url
        return self.avatar.url if self.avatar else ""

    def __str__(self):
        return self.display_name


class Notification(models.Model):
    class Kind(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ALERT = "alert", "Alert"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.INFO)
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]

    def __str__(self):
        return self.title
