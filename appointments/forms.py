from django import forms

from core.forms import StyledFormMixin

from .models import Appointment


class IntakeForm(StyledFormMixin, forms.Form):
    """Pre-visit digital intake, filled in while booking."""

    mode = forms.ChoiceField(choices=Appointment.Mode.choices, widget=forms.RadioSelect)
    reason = forms.CharField(
        label="What brings you in?", max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Persistent headache and dizziness"}),
    )
    symptoms = forms.CharField(
        label="Describe your symptoms", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "When did it start? What makes it better or worse?"}),
    )
    severity = forms.IntegerField(label="How bad is it right now?", min_value=1, max_value=10, initial=3,
                                  widget=forms.NumberInput(attrs={"type": "range", "min": 1, "max": 10, "step": 1}))
    symptom_duration = forms.ChoiceField(label="How long has this been going on?",
                                         choices=Appointment.SymptomDuration.choices, initial="days")
    consent = forms.BooleanField(
        label="I confirm this information is accurate and consent to sharing it with my doctor.",
    )

    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if doctor is not None:
            allowed = []
            if doctor.offers_in_person:
                allowed.append(Appointment.Mode.IN_PERSON)
            if doctor.offers_video:
                allowed.append(Appointment.Mode.VIDEO)
            self.fields["mode"].choices = [(m.value, m.label) for m in allowed]
            if len(allowed) == 1:
                self.fields["mode"].initial = allowed[0].value


class CancelForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=200, required=False,
                             widget=forms.TextInput(attrs={"placeholder": "Optional — helps the clinic plan"}))
