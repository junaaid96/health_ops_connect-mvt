from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils.text import slugify


class Specialty(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    description = models.CharField(max_length=240, blank=True)
    icon = models.CharField(max_length=40, default="stethoscope", help_text="Lucide icon name")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "specialties"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("clinic:directory") + f"?specialty={self.slug}"


class DoctorQuerySet(models.QuerySet):
    def listed(self):
        return self.filter(is_verified=True, user__is_active=True)

    def with_ratings(self):
        return self.annotate(
            rating_avg=Avg("reviews__rating"),
            rating_count=Count("reviews", distinct=True),
        )


class Doctor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor")
    slug = models.SlugField(max_length=120, unique=True)
    specialty = models.ForeignKey(Specialty, on_delete=models.PROTECT, related_name="doctors")
    title = models.CharField(max_length=80, default="Consultant", help_text="e.g. Senior Consultant")
    qualifications = models.CharField(max_length=160, blank=True, help_text="e.g. MBBS, FCPS (Medicine)")
    bio = models.TextField(blank=True)
    years_experience = models.PositiveSmallIntegerField(default=1)
    languages = models.CharField(max_length=120, default="English")
    license_number = models.CharField(max_length=40, blank=True)
    fee = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    photo = models.ImageField(upload_to="doctors/", blank=True)
    room = models.CharField(max_length=60, blank=True, help_text="Where in-person visits happen")
    offers_in_person = models.BooleanField(default=True)
    offers_video = models.BooleanField(default=True)
    video_link = models.URLField(blank=True, help_text="Optional personal meeting room. Leave blank for auto-generated rooms.")
    is_verified = models.BooleanField(default=False, help_text="Only verified doctors are listed and bookable.")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = DoctorQuerySet.as_manager()

    class Meta:
        ordering = ["user__first_name", "user__last_name"]

    def __str__(self):
        return self.user.display_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"dr {self.user.first_name} {self.user.last_name}") or slugify(self.user.username)
            slug, n = base, 2
            while Doctor.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("clinic:doctor", args=[self.slug])

    @property
    def name(self):
        return self.user.display_name

    @property
    def language_list(self):
        return [lang.strip() for lang in self.languages.split(",") if lang.strip()]

    @property
    def default_slot_minutes(self):
        blocks = list(self.availability.all())  # uses prefetch cache when present
        return blocks[0].slot_minutes if blocks else 20


class WeeklyAvailability(models.Model):
    """A recurring block of clinic hours, split into fixed-length slots."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="availability")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(5), MaxValueValidator(120)]
    )

    class Meta:
        ordering = ["weekday", "start_time"]
        verbose_name_plural = "weekly availability"

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time.")

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class TimeOff(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="time_off")
    date = models.DateField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["doctor", "date"], name="uniq_doctor_time_off")]

    def __str__(self):
        return f"{self.doctor} off on {self.date}"


class Review(models.Model):
    appointment = models.OneToOneField("appointments.Appointment", on_delete=models.CASCADE, related_name="review")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="reviews")
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}★ for {self.doctor}"
