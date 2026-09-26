from django import forms
from django.contrib.auth import get_user_model

from clinic.models import Doctor
from core.forms import StyledFormMixin

from .models import Admission, Bed

User = get_user_model()


class AdmissionForm(StyledFormMixin, forms.ModelForm):
    patient = forms.ModelChoiceField(
        queryset=User.objects.none(),
        empty_label="Select patient",
    )
    bed = forms.ModelChoiceField(queryset=Bed.objects.none(), empty_label="Select an available bed")
    attending = forms.ModelChoiceField(queryset=Doctor.objects.listed().select_related("user"), required=False,
                                       empty_label="Attending doctor (optional)")

    class Meta:
        model = Admission
        fields = ("patient", "bed", "attending", "reason")
        widgets = {"reason": forms.TextInput(attrs={"placeholder": "e.g. Post-operative observation"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = (
            User.objects.filter(role=User.Role.PATIENT, is_active=True)
            .exclude(pk__in=Admission.objects.filter(discharged_at__isnull=True).values("patient"))
            .order_by("first_name", "last_name")
        )
        self.fields["bed"].queryset = Bed.objects.filter(
            status__in=[Bed.Status.AVAILABLE, Bed.Status.RESERVED]).select_related("ward")
        self.fields["patient"].label_from_instance = lambda u: f"{u.get_full_name()} · {u.email}"
