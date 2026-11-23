from django import forms

from accounts.models import Player

from . import rules
from .models import Division, Event, Level, OrganizationDefaults

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
NUMBER = {"inputmode": "numeric"}


class EventForm(forms.ModelForm):
    """Create and edit an event (section 4).

    Matches per team and total matches are linked. Change one and the other
    is recalculated. The same goes for end date and number of weeks.
    """

    groups = [
        ("The basics", ["title", "level", "division", "location"]),
        ("When", ["start_date", "weeks", "end_date", "weekly_day", "start_time"]),
        ("Teams and matches", ["team_count", "matches_per_team", "total_matches", "scramble_rounds", "court_count", "pool_size"]),
        ("Scoring", ["games_per_match", "points_to_win", "win_by_two", "point_cap", "forfeit_points", "players_enter_scores"]),
        ("Timing", ["minutes_per_match", "break_minutes"]),
        ("Sign-ups", ["registration_mode", "max_participants"]),
        ("Bracket", ["bracket_type", "bracket_sizing", "third_place_match"]),
    ]

    class Meta:
        model = Event
        fields = [
            "title", "level", "division", "location",
            "start_date", "weeks", "end_date", "weekly_day", "start_time",
            "team_count", "matches_per_team", "total_matches", "scramble_rounds", "court_count", "pool_size",
            "games_per_match", "points_to_win", "win_by_two", "point_cap", "forfeit_points", "players_enter_scores",
            "minutes_per_match", "break_minutes",
            "registration_mode", "max_participants",
            "bracket_type", "bracket_sizing", "third_place_match",
        ]
        widgets = {
            "start_date": DATE,
            "end_date": DATE,
            "start_time": TIME,
        }
        help_texts = {
            "weeks": "Use 1 for a one-day event.",
            "end_date": "Or set the end date and the weeks fill in.",
            "weekly_day": "For multi-week events. Leave blank to use the start date's day.",
            "team_count": "You can set this before anyone signs up. Not used for Scramble.",
            "matches_per_team": "Change this or the total. The other one updates. For multi-week events, this is per week.",
            "scramble_rounds": "Scramble only. Everyone gets new partners each round.",
            "court_count": "1 to 8.",
            "max_participants": "Up to 500.",
            "pool_size": "Optional. For big events, teams per pool, like 6.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["end_date"].required = False
        self.fields["weeks"].required = False
        for name in ["weeks", "team_count", "matches_per_team", "total_matches", "scramble_rounds", "court_count",
                     "pool_size", "points_to_win", "point_cap", "forfeit_points", "minutes_per_match",
                     "break_minutes", "max_participants"]:
            self.fields[name].widget.attrs.update(NUMBER)
        self.fields["court_count"].widget.attrs.update(min=1, max=8)
        self.fields["max_participants"].widget.attrs.update(max=500)

    def grouped_fields(self):
        return [(title, [self[name] for name in names]) for title, names in self.groups]

    def clean(self):
        data = super().clean()
        self._clean_dates(data)
        self._clean_matches(data)
        self._clean_scoring(data)
        return data

    def _clean_dates(self, data):
        start = data.get("start_date")
        weeks = data.get("weeks")
        end = data.get("end_date")
        if not start:
            return
        changed = set(self.changed_data)
        use_end = end and ("end_date" in changed and "weeks" not in changed or not weeks)
        if use_end:
            try:
                data["weeks"] = rules.weeks_from_end_date(start, end)
            except ValueError as exc:
                self.add_error("end_date", str(exc))
                return
        else:
            data["weeks"] = weeks or 1
            data["end_date"] = rules.end_date_from_weeks(start, data["weeks"])
        if data["weeks"] > 1 and data.get("weekly_day") is None:
            data["weekly_day"] = start.weekday()

    def _clean_matches(self, data):
        division = data.get("division")
        teams = data.get("team_count")
        per_team = data.get("matches_per_team")
        total = data.get("total_matches")
        if division and division.is_scramble:
            if not data.get("scramble_rounds"):
                self.add_error("scramble_rounds", "Enter how many rounds to play.")
            return
        if not teams:
            self.add_error("team_count", "Enter how many teams will play.")
            return
        if not per_team and not total:
            self.add_error("matches_per_team", "Enter matches per team or total matches.")
            return
        changed = set(self.changed_data)
        use_total = total and ("total_matches" in changed and "matches_per_team" not in changed or not per_team)
        if use_total:
            data["matches_per_team"] = rules.per_team_from_total(teams, total)
            if data["matches_per_team"] < 1:
                self.add_error("total_matches", "That's not enough matches for every team to play once.")
        else:
            data["total_matches"] = rules.total_from_per_team(teams, per_team)

    def _clean_scoring(self, data):
        cap = data.get("point_cap")
        to_win = data.get("points_to_win")
        if cap and to_win and cap <= to_win:
            self.add_error("point_cap", "The cap must be higher than the points to win.")


class QuickCreateForm(forms.Form):
    level = forms.ModelChoiceField(Level.objects.all(), empty_label=None)
    division = forms.ModelChoiceField(Division.objects.all(), empty_label=None)
    start_date = forms.DateField(widget=DATE)
    weeks = forms.IntegerField(min_value=1, max_value=52, initial=1, widget=forms.NumberInput(attrs=NUMBER),
                               help_text="Use 1 for a one-day event.")


class DefaultsForm(forms.ModelForm):
    class Meta:
        model = OrganizationDefaults
        exclude = ["updated_at"]
        widgets = {"start_time": TIME}


class AdminAddPlayerForm(forms.Form):
    player = forms.ModelChoiceField(Player.objects.none(), label="Player")
    override = forms.BooleanField(label="Override (skip gender and size checks)", required=False)

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["player"].queryset = Player.objects.exclude(registrations__event=event)


class MovePlayerForm(forms.Form):
    to_event = forms.ModelChoiceField(Event.objects.none(), label="Move to")
    override = forms.BooleanField(label="Override", required=False)

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_event"].queryset = Event.objects.exclude(pk=event.pk).select_related("level", "division")


class BuildTeamForm(forms.Form):
    player_a = forms.ModelChoiceField(Player.objects.none(), label="Player 1")
    player_b = forms.ModelChoiceField(Player.objects.none(), label="Player 2")
    override = forms.BooleanField(label="Override (skip gender and team-count checks)", required=False)

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        free = Player.objects.filter(registrations__event=event).exclude(sides__event=event)
        self.fields["player_a"].queryset = free
        self.fields["player_b"].queryset = free


class CodeForm(forms.Form):
    code = forms.CharField(max_length=20, label="Code",
                           widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off",
                                                         "placeholder": "ABC123"}))


class InviteForm(forms.Form):
    username = forms.CharField(max_length=150, label="Partner's username",
                               widget=forms.TextInput(attrs={"autocapitalize": "none"}))
