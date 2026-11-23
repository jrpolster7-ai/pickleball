from django import forms

from events.models import MAX_COURTS

TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class RoundTimeForm(forms.Form):
    start_time = forms.TimeField(label="Start time", widget=TIME)


class MatchEditForm(forms.Form):
    start_time = forms.TimeField(label="Start time", widget=TIME)
    court = forms.IntegerField(min_value=1, max_value=MAX_COURTS, label="Court",
                               widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": 1, "max": MAX_COURTS}))
