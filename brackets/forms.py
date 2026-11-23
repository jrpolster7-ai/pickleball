from django import forms
from django.core.validators import MaxValueValidator

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class AdvanceForm(forms.Form):
    count = forms.IntegerField(
        label="Teams that advance", min_value=2,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": 2}),
    )
    date = forms.DateField(label="Bracket date", required=False, widget=DATE,
                           help_text="Leave blank for the last round robin day.")
    start_time = forms.TimeField(label="First bracket match", required=False, widget=TIME,
                                 help_text="Leave blank to start right after the last round.")

    def __init__(self, *args, team_count: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["count"].max_value = team_count
        self.fields["count"].widget.attrs["max"] = team_count
        self.fields["count"].validators.append(MaxValueValidator(team_count))
