import segno
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from appointments import services
from appointments.models import Appointment
from core.permissions import clinician_required, doctor_required, patient_required

from .forms import ConsultationForm, HealthProfileForm, PrescriptionFormSet, VitalReadingForm
from .models import AccessLog, Consultation, HealthProfile, PrescriptionItem

User = get_user_model()

COMMON_MEDICINES = [
    "Paracetamol", "Ibuprofen", "Amoxicillin", "Azithromycin", "Cetirizine", "Omeprazole", "Esomeprazole",
    "Metformin", "Amlodipine", "Losartan", "Atorvastatin", "Salbutamol inhaler", "Montelukast",
    "Pantoprazole", "Domperidone", "Loratadine", "Vitamin D3", "Oral rehydration salts", "Hydrocortisone cream",
]


def vitals_series(readings):
    """Chart configs (oldest first) for the vitals small multiples: one chart
    per measure, so each keeps its own honest y-axis."""
    rows = sorted(readings, key=lambda r: r.recorded_at)

    def label(r):
        return timezone.localtime(r.recorded_at).strftime("%d %b")

    def single(attr, name, unit):
        pts = [r for r in rows if getattr(r, attr) is not None]
        return {"labels": [label(r) for r in pts], "unit": unit,
                "series": [{"label": name, "data": [float(getattr(r, attr)) for r in pts]}]} if pts else None

    bp_rows = [r for r in rows if r.systolic and r.diastolic]
    charts = {
        "bp": {"labels": [label(r) for r in bp_rows], "unit": "mmHg", "series": [
            {"label": "Systolic", "data": [r.systolic for r in bp_rows], "slot": 0},
            {"label": "Diastolic", "data": [r.diastolic for r in bp_rows], "slot": 1},
        ]} if bp_rows else None,
        "heart_rate": single("heart_rate", "Heart rate", "bpm"),
        "glucose": single("glucose", "Glucose", "mg/dL"),
        "weight": single("weight_kg", "Weight", "kg"),
    }
    return {k: v for k, v in charts.items() if v}


@patient_required
def health(request):
    profile, _ = HealthProfile.objects.get_or_create(user=request.user)
    form = HealthProfileForm(request.POST or None, instance=profile, prefix="hp")
    vital_form = VitalReadingForm(prefix="v")
    if request.method == "POST":
        if request.POST.get("action") == "vitals":
            form = HealthProfileForm(instance=profile, prefix="hp")
            vital_form = VitalReadingForm(request.POST, prefix="v")
            if vital_form.is_valid():
                reading = vital_form.save(commit=False)
                reading.patient = reading.recorded_by = request.user
                reading.save()
                flags = reading.flags()
                if any(level == "critical" for _, level, _ in flags):
                    messages.warning(request, "Some readings are in a critical range. If you feel unwell, "
                                              "seek urgent care or book the earliest available doctor.")
                else:
                    messages.success(request, "Vitals logged.")
                return redirect("records:health")
        elif form.is_valid():
            form.save()
            messages.success(request, "Health passport saved.")
            return redirect("records:health")
    readings = list(request.user.vitals.all()[:60])
    return render(request, "records/health.html", {
        "profile": profile, "form": form, "vital_form": vital_form,
        "readings": readings[:10], "latest": readings[0] if readings else None,
        "series": vitals_series(readings),
    })


@require_POST
@patient_required
def delete_vital(request, pk):
    get_object_or_404(request.user.vitals, pk=pk).delete()
    messages.success(request, "Reading deleted.")
    return redirect("records:health")


def _patient_history(patient):
    return (Appointment.objects.filter(patient=patient)
            .select_related("doctor__user", "doctor__specialty", "consultation")
            .prefetch_related("consultation__items")
            .order_by("-scheduled_at"))


@clinician_required
def patient_chart(request, pk):
    patient = get_object_or_404(User, pk=pk, role=User.Role.PATIENT)
    user = request.user
    if user.is_doctor and not user.is_ops and not patient.appointments.filter(doctor=user.doctor).exists():
        raise Http404
    AccessLog.record(request, patient, AccessLog.Action.VIEW_CHART)
    readings = list(patient.vitals.all()[:60])
    return render(request, "records/patient_chart.html", {
        "patient": patient,
        "profile": HealthProfile.objects.get_or_create(user=patient)[0],
        "history": _patient_history(patient)[:30],
        "readings": readings[:10],
        "latest": readings[0] if readings else None,
        "series": vitals_series(readings),
    })


@doctor_required
def consult(request, code):
    appt = get_object_or_404(
        Appointment.objects.select_related("patient", "doctor__user", "doctor__specialty"),
        code=code, doctor=request.user.doctor,
    )
    patient = appt.patient
    profile, _ = HealthProfile.objects.get_or_create(user=patient)
    existing = getattr(appt, "consultation", None)
    form = ConsultationForm(request.POST or None, instance=existing, prefix="c")
    formset = PrescriptionFormSet(request.POST or None, prefix="rx", initial=[
        {f: getattr(i, f) for f in ("medicine", "dosage", "frequency", "duration", "instructions")}
        for i in (existing.items.all() if existing else [])
    ])
    vital_form = VitalReadingForm(prefix="v")
    conflicts = []
    action = request.POST.get("action")

    if request.method == "POST" and action == "start":
        try:
            services.start_consultation(appt)
            messages.success(request, f"Consultation with {patient.display_name} started.")
        except services.BookingError as exc:
            messages.error(request, str(exc))
        return redirect("records:consult", code=code)

    if request.method == "POST" and action == "vitals":
        vital_form = VitalReadingForm(request.POST, prefix="v")
        if vital_form.is_valid():
            reading = vital_form.save(commit=False)
            reading.patient, reading.recorded_by = patient, request.user
            reading.save()
            AccessLog.record(request, patient, AccessLog.Action.RECORD_VITALS, f"During visit {appt.code}")
            messages.success(request, "Vitals recorded.")
            return redirect("records:consult", code=code)
        form = ConsultationForm(instance=existing, prefix="c")
        formset = PrescriptionFormSet(prefix="rx")

    elif request.method == "POST" and action == "complete":
        if appt.status not in (Appointment.Status.IN_PROGRESS, Appointment.Status.COMPLETED):
            messages.error(request, "Start the consultation before completing it.")
            return redirect("records:consult", code=code)
        if form.is_valid() and formset.is_valid():
            items = [f.cleaned_data for f in formset if f.cleaned_data.get("medicine")]
            conflicts = profile.allergy_conflicts([i["medicine"] for i in items])
            if conflicts and not form.cleaned_data.get("confirm_allergy_override"):
                messages.error(request, "Allergy warning — review the highlighted medicines before continuing.")
            else:
                with transaction.atomic():
                    consultation = form.save(commit=False)
                    consultation.appointment = appt
                    consultation.allergy_override = bool(conflicts)
                    consultation.save()
                    consultation.items.all().delete()
                    PrescriptionItem.objects.bulk_create(
                        PrescriptionItem(consultation=consultation, **i) for i in items)
                    first_completion = appt.status != Appointment.Status.COMPLETED
                    if first_completion:
                        services.complete(appt)
                AccessLog.record(request, patient, AccessLog.Action.PRESCRIBE,
                                 f"{consultation.diagnosis} · {len(items)} medicine(s)")
                messages.success(request, "Visit completed and prescription issued." if first_completion
                                 else "Visit notes updated.")
                state = services.queue_for(appt.doctor)
                if state.waiting and first_completion:
                    return redirect("core:dashboard")
                return redirect("records:consult", code=code)
    else:
        AccessLog.record(request, patient, AccessLog.Action.CONSULT, f"Visit {appt.code}")

    readings = list(patient.vitals.all()[:30])
    return render(request, "records/consult.html", {
        "appt": appt,
        "patient": patient,
        "profile": profile,
        "form": form,
        "formset": formset,
        "vital_form": vital_form,
        "conflicts": conflicts,
        "conflict_medicines": {c[0].lower() for c in conflicts},
        "history": _patient_history(patient).exclude(pk=appt.pk)[:8],
        "latest": readings[0] if readings else None,
        "series": vitals_series(readings),
        "common_medicines": COMMON_MEDICINES,
        "is_today": appt.local_date == services.local_today(),
    })


def _qr_svg(url):
    qr = segno.make(url, error="m")
    return mark_safe(qr.svg_inline(scale=3, dark="#0f172a", light=None, border=1))


@login_required
def prescription(request, code):
    consultation = get_object_or_404(
        Consultation.objects.select_related("appointment__patient", "appointment__doctor__user",
                                            "appointment__doctor__specialty"),
        appointment__code=code,
    )
    appt = consultation.appointment
    user = request.user
    if not (appt.patient == user or user.is_ops or (user.is_doctor and appt.doctor.user == user)):
        raise Http404
    profile = HealthProfile.objects.filter(user=appt.patient).first()
    return render(request, "records/prescription.html", {
        "c": consultation, "appt": appt, "profile": profile, "qr": _qr_svg(consultation.verify_url),
    })


def verify(request, code):
    """Public: pharmacies scan the QR to confirm a prescription is genuine.
    Shows only what's needed to verify — no diagnosis or full name."""
    consultation = Consultation.objects.select_related(
        "appointment__patient", "appointment__doctor__user", "appointment__doctor__specialty"
    ).filter(verification_code=code.upper()).first()
    return render(request, "records/verify.html", {"c": consultation, "code": code})


@patient_required
def prescriptions(request):
    items = (Consultation.objects.filter(appointment__patient=request.user)
             .select_related("appointment__doctor__user", "appointment__doctor__specialty")
             .prefetch_related("items"))
    return render(request, "records/prescriptions.html", {"items": items})


@patient_required
def privacy(request):
    logs = request.user.access_logs.select_related("actor")[:200]
    return render(request, "records/privacy.html", {"logs": logs})
