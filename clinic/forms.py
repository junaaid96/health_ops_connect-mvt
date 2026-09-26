from django import forms
from django.forms import inlineformset_factory

from core.forms import StyledFormMixin

from .models import Doctor, Review, TimeOff, WeeklyAvailability


class AvailabilityForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = WeeklyAvailability
        fields = ("weekday", "start_time", "end_time", "slot_minutes")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }


AvailabilityFormSet = inlineformset_factory(
    Doctor, WeeklyAvailability, form=AvailabilityForm, extra=1, can_delete=True, max_num=28
)


class TimeOffForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TimeOff
        fields = ("date", "reason")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class DoctorProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Doctor
        fields = ("title", "qualifications", "bio", "years_experience", "languages", "fee", "room",
                  "offers_in_person", "offers_video", "video_link", "photo")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("offers_in_person") and not cleaned.get("offers_video"):
            raise forms.ValidationError("Offer at least one visit type (in-person or video).")
        return cleaned


class ReviewForm(StyledFormMixin, forms.ModelForm):
    rating = forms.TypedChoiceField(choices=[(i, i) for i in range(5, 0, -1)], coerce=int,
                                    widget=forms.RadioSelect)

    class Meta:
        model = Review
        fields = ("rating", "comment")
        widgets = {"comment": forms.Textarea(attrs={"rows": 3, "placeholder": "What went well? What could be better?"})}
