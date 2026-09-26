from datetime import date as date_cls

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from appointments import services
from appointments.models import Appointment
from core.permissions import doctor_required, patient_required

from . import triage
from .forms import AvailabilityFormSet, DoctorProfileForm, ReviewForm, TimeOffForm
from .models import Doctor, Specialty, TimeOff

SORTS = {
    "recommended": "Recommended",
    "soonest": "Soonest available",
    "rating": "Highest rated",
    "fee_asc": "Fee: low to high",
    "fee_desc": "Fee: high to low",
    "experience": "Most experienced",
}


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def directory(request):
    doctors = Doctor.objects.listed().with_ratings().select_related("user", "specialty")
    q = request.GET.get("q", "").strip()
    specialty = request.GET.get("specialty", "")
    mode = request.GET.get("mode", "")
    max_fee = request.GET.get("max_fee", "")
    available = request.GET.get("available", "")
    sort = request.GET.get("sort", "recommended")

    if q:
        doctors = doctors.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
            | Q(specialty__name__icontains=q) | Q(qualifications__icontains=q)
            | Q(bio__icontains=q) | Q(languages__icontains=q)
        )
    if specialty:
        doctors = doctors.filter(specialty__slug=specialty)
    if mode == "video":
        doctors = doctors.filter(offers_video=True)
    elif mode == "in_person":
        doctors = doctors.filter(offers_in_person=True)
    if max_fee.isdigit():
        doctors = doctors.filter(fee__lte=int(max_fee))

    doctors = list(doctors)
    days = services.booking_days(days=1 if available == "today" else 7 if available == "week" else None)
    soonest = services.next_available(doctors, days=days)
    if available:
        doctors = [d for d in doctors if soonest.get(d.pk)]

    far = date_cls.max
    if sort == "soonest":
        doctors.sort(key=lambda d: (soonest.get(d.pk) is None, soonest.get(d.pk) or far))
    elif sort == "rating":
        doctors.sort(key=lambda d: (-(d.rating_avg or 0), -d.rating_count))
    elif sort == "fee_asc":
        doctors.sort(key=lambda d: d.fee)
    elif sort == "fee_desc":
        doctors.sort(key=lambda d: -d.fee)
    elif sort == "experience":
        doctors.sort(key=lambda d: -d.years_experience)
    else:
        # Recommended: bookable soon first, then rating.
        doctors.sort(key=lambda d: (soonest.get(d.pk) is None, -(d.rating_avg or 0)))

    page = Paginator(doctors, 12).get_page(request.GET.get("page"))
    ctx = {
        "page": page,
        "soonest": soonest,
        "total": len(doctors),
        "specialties": Specialty.objects.annotate(n=Count("doctors", filter=Q(doctors__is_verified=True))),
        "sorts": SORTS,
        "filters": {"q": q, "specialty": specialty, "mode": mode, "max_fee": max_fee,
                    "available": available, "sort": sort},
    }
    template = "clinic/_doctor_results.html" if _is_htmx(request) else "clinic/directory.html"
    return render(request, template, ctx)


def _pick_day(request, calendar):
    wanted = request.GET.get("date")
    days = [d for d, _, _ in calendar]
    if wanted:
        try:
            day = date_cls.fromisoformat(wanted)
            if day in days:
                return day
        except ValueError:
            pass
    return next((d for d, open_count, _ in calendar if open_count), days[0])


def doctor_detail(request, slug):
    doctor = get_object_or_404(
        Doctor.objects.with_ratings().select_related("user", "specialty").prefetch_related("availability"), slug=slug
    )
    if not doctor.is_verified and not (request.user.is_authenticated and
                                        (request.user == doctor.user or request.user.is_ops)):
        return render(request, "clinic/doctor_unavailable.html", {"doctor": doctor}, status=404)
    calendar = services.calendar_for(doctor)
    day = _pick_day(request, calendar)
    reviews = doctor.reviews.select_related("patient")
    distribution = {i: 0 for i in range(5, 0, -1)}
    for row in reviews.values("rating").annotate(n=Count("id")):
        distribution[row["rating"]] = row["n"]
    ctx = {
        "doctor": doctor,
        "calendar": calendar,
        "day": day,
        "slots": services.slots_for_day(doctor, day),
        "reviews": reviews.exclude(comment="")[:8],
        "distribution": distribution,
        "on_waitlist": request.user.is_authenticated and doctor.waitlist.filter(patient=request.user, date=day).exists(),
        "mode": request.GET.get("mode") or ("in_person" if doctor.offers_in_person else "video"),
        "reschedule": None,
    }
    return render(request, "clinic/doctor_detail.html", ctx)


def doctor_slots(request, slug):
    """htmx partial: slot grid for one day (also used when rescheduling)."""
    doctor = get_object_or_404(Doctor.objects.select_related("user"), slug=slug)
    reschedule = None
    if code := request.GET.get("reschedule"):
        if request.user.is_authenticated:
            reschedule = Appointment.objects.filter(code=code, patient=request.user, doctor=doctor).first()
    calendar = services.calendar_for(doctor, exclude_pk=reschedule.pk if reschedule else None)
    day = _pick_day(request, calendar)
    ctx = {
        "doctor": doctor,
        "day": day,
        "calendar": calendar,
        "slots": services.slots_for_day(doctor, day, exclude_pk=reschedule.pk if reschedule else None),
        "on_waitlist": request.user.is_authenticated and doctor.waitlist.filter(patient=request.user, date=day).exists(),
        "mode": request.GET.get("mode", ""),
        "reschedule": reschedule,
    }
    return render(request, "clinic/_slot_picker.html", ctx)


@patient_required
@require_POST
def join_waitlist(request, slug):
    doctor = get_object_or_404(Doctor.objects.listed(), slug=slug)
    try:
        day = date_cls.fromisoformat(request.POST.get("date", ""))
        _, created = services.join_waitlist(request.user, doctor, day)
    except (ValueError, services.BookingError) as exc:
        messages.error(request, str(exc) or "Invalid date.")
        return redirect(doctor.get_absolute_url())
    if created:
        messages.success(request, f"You're on the waitlist for {day:%A %d %b}. We'll notify you the moment a slot opens.")
    else:
        messages.info(request, "You're already on the waitlist for that day.")
    return redirect(doctor.get_absolute_url() + f"?date={day.isoformat()}")


def care_finder(request):
    text = request.GET.get("symptoms", "").strip()
    severity = request.GET.get("severity") or None
    result = None
    recommendations = []
    if text:
        result = triage.analyze(text, severity=severity)
        specialties = {s.slug: s for s in Specialty.objects.filter(slug__in=result.top_slugs)}
        for match in result.matches:
            spec = specialties.get(match.slug)
            if not spec:
                continue
            docs = list(Doctor.objects.listed().with_ratings().select_related("user", "specialty")
                        .filter(specialty=spec))
            soonest = services.next_available(docs)
            docs.sort(key=lambda d: (soonest.get(d.pk) is None, soonest.get(d.pk) or date_cls.max))
            recommendations.append({"specialty": spec, "match": match, "doctors": docs[:3], "soonest": soonest})
    ctx = {
        "text": text,
        "severity": severity or "3",
        "result": result,
        "recommendations": recommendations,
        "examples": [
            "Headache and dizziness for 3 days",
            "Itchy red rash on my arms",
            "My child has a fever and cough",
            "Knee pain after running",
            "Feeling anxious and can't sleep",
        ],
    }
    template = "clinic/_care_results.html" if _is_htmx(request) else "clinic/care_finder.html"
    return render(request, template, ctx)


@doctor_required
def schedule(request):
    doctor = request.user.doctor
    formset = AvailabilityFormSet(request.POST or None, instance=doctor, prefix="avail")
    time_off_form = TimeOffForm(prefix="off")
    profile_form = DoctorProfileForm(instance=doctor, prefix="profile")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "availability" and formset.is_valid():
            formset.save()
            messages.success(request, "Weekly schedule saved. Patients can book the new slots right away.")
            return redirect("clinic:schedule")
        if action == "time_off":
            formset = AvailabilityFormSet(instance=doctor, prefix="avail")
            time_off_form = TimeOffForm(request.POST, prefix="off")
            if time_off_form.is_valid():
                off = time_off_form.save(commit=False)
                off.doctor = doctor
                if TimeOff.objects.filter(doctor=doctor, date=off.date).exists():
                    messages.info(request, "You already have that day off.")
                else:
                    off.save()
                    clashes = doctor.appointments.on_date(off.date).filter(
                        status=Appointment.Status.BOOKED).count()
                    msg = f"Time off added for {off.date:%a %d %b}."
                    if clashes:
                        msg += f" {clashes} existing booking(s) that day still need to be rescheduled or cancelled."
                    messages.success(request, msg)
                return redirect("clinic:schedule")
        if action == "profile":
            formset = AvailabilityFormSet(instance=doctor, prefix="avail")
            profile_form = DoctorProfileForm(request.POST, request.FILES, instance=doctor, prefix="profile")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Public profile updated.")
                return redirect("clinic:schedule")
    ctx = {
        "doctor": doctor,
        "formset": formset,
        "time_off_form": time_off_form,
        "profile_form": profile_form,
        "time_off": doctor.time_off.filter(date__gte=services.local_today()),
        "calendar": services.calendar_for(doctor, days=services.booking_days(days=7)),
    }
    return render(request, "clinic/schedule.html", ctx)


@doctor_required
@require_POST
def delete_time_off(request, pk):
    get_object_or_404(TimeOff, pk=pk, doctor=request.user.doctor).delete()
    messages.success(request, "Time off removed.")
    return redirect("clinic:schedule")


@patient_required
@require_POST
def review(request, code):
    appt = get_object_or_404(Appointment, code=code, patient=request.user, status=Appointment.Status.COMPLETED)
    if hasattr(appt, "review"):
        messages.info(request, "You've already reviewed this visit.")
        return redirect(appt.get_absolute_url())
    form = ReviewForm(request.POST)
    if form.is_valid():
        r = form.save(commit=False)
        r.appointment, r.doctor, r.patient = appt, appt.doctor, request.user
        r.save()
        messages.success(request, "Thanks for your feedback — it helps other patients choose.")
    else:
        messages.error(request, "Please choose a star rating.")
    return redirect(appt.get_absolute_url())
