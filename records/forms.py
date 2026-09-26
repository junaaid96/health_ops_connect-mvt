from django import forms
from django.forms import formset_factory

from core.forms import StyledFormMixin

from .models import Consultation, HealthProfile, PrescriptionItem, VitalReading


class HealthProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = HealthProfile
        exclude = ("user", "updated_at")
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "allergies": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. penicillin, peanuts — or \"none\""}),
            "chronic_conditions": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. type 2 diabetes, asthma"}),
            "current_medications": forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. metformin 500 mg"}),
        }


class VitalReadingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VitalReading
        fields = ("systolic", "diastolic", "heart_rate", "glucose", "temperature", "spo2", "weight_kg", "note")
        widgets = {"note": forms.TextInput(attrs={"placeholder": "Optional — e.g. after morning walk"})}

    def clean(self):
        cleaned = super().clean()
        metrics = [f for f in self.Meta.fields if f != "note"]
        if not any(cleaned.get(f) not in (None, "") for f in metrics):
            raise forms.ValidationError("Enter at least one measurement.")
        if bool(cleaned.get("systolic")) != bool(cleaned.get("diastolic")):
            raise forms.ValidationError("Blood pressure needs both systolic and diastolic values.")
        return cleaned


class ConsultationForm(StyledFormMixin, forms.ModelForm):
    confirm_allergy_override = forms.BooleanField(
        required=False, label="I have reviewed the allergy warning and want to prescribe anyway.")

    class Meta:
        model = Consultation
        fields = ("diagnosis", "clinical_notes", "advice", "follow_up_in_days")
        widgets = {
            "clinical_notes": forms.Textarea(attrs={"rows": 4, "placeholder": "History, examination, assessment (visible to clinicians only)"}),
            "advice": forms.Textarea(attrs={"rows": 3, "placeholder": "Plain-language advice shown to the patient"}),
            "follow_up_in_days": forms.NumberInput(attrs={"placeholder": "e.g. 14", "min": 1, "max": 365}),
        }
        labels = {"follow_up_in_days": "Follow-up in (days)"}


class PrescriptionItemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PrescriptionItem
        fields = ("medicine", "dosage", "frequency", "duration", "instructions")
        widgets = {
            "medicine": forms.TextInput(attrs={"placeholder": "Paracetamol", "list": "common-medicines"}),
            "dosage": forms.TextInput(attrs={"placeholder": "500 mg"}),
            "frequency": forms.TextInput(attrs={"placeholder": "1-0-1 after meals"}),
            "duration": forms.TextInput(attrs={"placeholder": "5 days"}),
            "instructions": forms.TextInput(attrs={"placeholder": "Optional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # An empty row is allowed; filled rows need the essentials.
        for name in ("medicine", "dosage", "frequency", "duration"):
            self.fields[name].required = False
            self.fields[name].widget.attrs.pop("required", None)

    def clean(self):
        cleaned = super().clean()
        filled = [cleaned.get(f) for f in ("medicine", "dosage", "frequency", "duration")]
        if any(filled) and not all(filled):
            raise forms.ValidationError("Fill in medicine, dosage, frequency and duration.")
        return cleaned


PrescriptionFormSet = formset_factory(PrescriptionItemForm, extra=1, max_num=15)
