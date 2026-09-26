from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from appointments import services
from appointments.models import Appointment
from clinic.models import Doctor, Review, Specialty
from core.permissions import doctor_required
from records.models import Consultation, HealthProfile

Status = Appointment.Status


def home(request):
    doctors = list(Doctor.objects.listed().with_ratings().select_related("user", "specialty")
                   .order_by("-rating_avg")[:8])
    stats = {
        "doctors": Doctor.objects.listed().count(),
        "specialties": Specialty.objects.filter(doctors__is_verified=True).distinct().count(),
        "visits": Appointment.objects.filter(status=Status.COMPLETED).count(),
        "rating": Review.objects.aggregate(a=Avg("rating"))["a"],
    }
    return render(request, "core/home.html", {
        "doctors": doctors,
        "soonest": services.next_available(doctors),
        "specialties": Specialty.objects.annotate(n=Count("doctors", filter=Q(doctors__is_verified=True))).filter(n__gt=0),
        "stats": stats,
        "testimonials": Review.objects.filter(rating__gte=4).exclude(comment="")
        .select_related("patient", "doctor__user")[:3],
    })


@login_required
def dashboard(request):
    user = request.user
    if user.is_ops:
        return redirect("operations:dashboard")
    if user.is_doctor:
        return doctor_dashboard(request)
    return patient_dashboard(request)


def patient_dashboard(request):
    user = request.user
    profile, _ = HealthProfile.objects.get_or_create(user=user)
    upcoming = list(Appointment.objects.filter(patient=user).upcoming()
                    .select_related("doctor__user", "doctor__specialty")[:4])
    next_appt = upcoming[0] if upcoming else None
    queue_entry = None
    if next_appt and next_appt.status == Status.CHECKED_IN:
        queue_entry = services.queue_for(next_appt.doctor, next_appt.local_date).position_of(next_appt)
    latest_vitals = user.vitals.first()
    to_review = (Appointment.objects.filter(patient=user, status=Status.COMPLETED, review__isnull=True)
                 .select_related("doctor__user").order_by("-completed_at").first())
    follow_up = (Consultation.objects.filter(appointment__patient=user, follow_up_in_days__isnull=False)
                 .select_related("appointment__doctor__user").first())
    if follow_up and (not follow_up.follow_up_date or follow_up.follow_up_date < services.local_today()
                      or Appointment.objects.filter(patient=user, doctor=follow_up.appointment.doctor,
                                                    created_at__gt=follow_up.created_at).exists()):
        follow_up = None
    return render(request, "core/patient_dashboard.html", {
        "profile": profile,
        "next_appt": next_appt,
        "upcoming": upcoming[1:],
        "queue_entry": queue_entry,
        "latest_vitals": latest_vitals,
        "vital_flags": latest_vitals.flags() if latest_vitals else [],
        "recent_rx": Consultation.objects.filter(appointment__patient=user)
        .select_related("appointment__doctor__user").prefetch_related("items")[:3],
        "to_review": to_review,
        "follow_up": follow_up,
        "visits_count": Appointment.objects.filter(patient=user, status=Status.COMPLETED).count(),
        "now": timezone.now(),
    })


def doctor_dashboard(request):
    doctor = request.user.doctor
    today = services.local_today()
    now = timezone.now()
    todays = list(Appointment.objects.filter(doctor=doctor).on_date(today)
                  .exclude(status=Status.CANCELLED).select_related("patient", "patient__health")
                  .order_by("scheduled_at"))
    queue = services.queue_for(doctor, today, now=now)
    week_start = today - timedelta(days=6)
    week = Appointment.objects.filter(doctor=doctor, scheduled_at__date__gte=week_start, scheduled_at__date__lte=today)
    stats = week.aggregate(
        seen=Count("id", filter=Q(status=Status.COMPLETED)),
        missed=Count("id", filter=Q(status=Status.NO_SHOW)),
        total=Count("id", filter=~Q(status=Status.CANCELLED)),
    )
    rating = doctor.reviews.aggregate(avg=Avg("rating"), n=Count("id"))
    trend_raw = dict(
        Appointment.objects.filter(doctor=doctor, status=Status.COMPLETED,
                                   scheduled_at__date__gte=today - timedelta(days=13))
        .values_list("scheduled_at__date").annotate(n=Count("id")).values_list("scheduled_at__date", "n")
    )
    trend = [{"label": (today - timedelta(days=13 - i)).strftime("%d %b"),
              "n": trend_raw.get(today - timedelta(days=13 - i), 0)} for i in range(14)]
    upcoming = (Appointment.objects.filter(doctor=doctor, scheduled_at__date__gt=today,
                                           status=Status.BOOKED)
                .select_related("patient").order_by("scheduled_at")[:6])
    return render(request, "core/doctor_dashboard.html", {
        "doctor": doctor,
        "todays": todays,
        "queue": queue,
        "stats": stats,
        "rating": rating,
        "trend": trend,
        "trend_chart": {"labels": [t["label"] for t in trend],
                        "series": [{"label": "Patients seen", "data": [t["n"] for t in trend]}]},
        "upcoming": upcoming,
        "remaining": sum(1 for a in todays if a.status in (Status.BOOKED, Status.CHECKED_IN)),
        "now": now,
        "has_schedule": doctor.availability.exists(),
    })


@doctor_required
def doctor_queue(request):
    """htmx partial: the doctor's live queue."""
    doctor = request.user.doctor
    return render(request, "core/_doctor_queue.html", {"queue": services.queue_for(doctor), "doctor": doctor})


@doctor_required
@require_POST
def call_next(request):
    try:
        appt = services.call_next(request.user.doctor)
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect("core:dashboard")
    messages.success(request, f"Now seeing {appt.patient.display_name} (token #{appt.token}).")
    return redirect("records:consult", code=appt.code)


def about(request):
    return render(request, "core/about.html")


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "error"
    return JsonResponse({"status": "ok" if db == "ok" else "degraded", "database": db},
                        status=200 if db == "ok" else 503)
