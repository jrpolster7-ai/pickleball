"""Seed 500 players and run full events from start to finish (CLAUDE.md section 13).

    python manage.py load_check            # build, play, and time the pages
    python manage.py load_check --clean    # remove everything a load check made

Everything it makes is named "loadcheck-..." or "Load check ...", so it never
touches real players or events. The data stays afterward so you can click
through it in the browser; run with --clean when you're done.
"""

import datetime
import random
import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse

from accounts.models import Gender, Player, User
from brackets import services as brackets
from chat import services as chat
from events import registration, teams
from events.models import Division, Event, Level
from scheduling import services as scheduling
from scheduling.models import Match
from scoring import services as scoring
from standings import services as standings

PREFIX = "loadcheck-"
TITLE = "Load check"
# A page using more queries than this probably has an N+1 problem.
QUERY_BUDGET = 40


class Command(BaseCommand):
    help = "Seed 500 players, run a full doubles event and a Scramble event, and time the main pages."

    def add_arguments(self, parser):
        parser.add_argument("--players", type=int, default=500, help="How many players (even number, max 500).")
        parser.add_argument("--clean", action="store_true", help="Delete load check data and stop.")
        parser.add_argument("--seed", type=int, default=7, help="Random seed for scores.")

    def handle(self, *args, players, clean, seed, **options):
        self.clean()
        if clean:
            self.stdout.write(self.style.SUCCESS("Load check data removed."))
            return
        players -= players % 2
        players = max(8, min(players, 500))
        self.rng = random.Random(seed)
        self.problems = []

        admin = self.step("Make an admin and players", lambda: self.make_people(players))
        doubles = self.step("Run a Mixed doubles event", lambda: self.run_doubles(admin, players))
        scramble = self.step("Run a Scramble event", lambda: self.run_scramble(admin, players))
        self.step("Post chat messages", lambda: self.chat(doubles, 200))
        self.time_pages(admin, doubles, scramble)

        if self.problems:
            self.stdout.write(self.style.WARNING("\nPages over the query budget:"))
            for p in self.problems:
                self.stdout.write(self.style.WARNING(f"  {p}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nEvery page stayed under {QUERY_BUDGET} queries."))
        self.stdout.write(f"\nThe data is kept so you can look around. Sign in as an admin and open "
                          f"'{TITLE}' events. Remove it with: python manage.py load_check --clean")

    # --- Helpers -----------------------------------------------------------

    def step(self, label, fn):
        start = time.perf_counter()
        result = fn()
        self.stdout.write(f"{label:<34} {time.perf_counter() - start:7.1f}s")
        return result

    def clean(self):
        events = Event.objects.filter(title__startswith=TITLE)
        Match.objects.filter(event__in=events).delete()  # Matches protect their teams, so they go first.
        events.delete()
        Player.objects.filter(user__username__startswith=PREFIX).delete()
        User.objects.filter(username__startswith=PREFIX).delete()

    def make_people(self, count):
        admin = User(username=f"{PREFIX}admin", first_name="Load", last_name="Check Admin", is_staff=True)
        admin.set_unusable_password()
        admin.save()
        users = []
        for i in range(1, count + 1):
            u = User(username=f"{PREFIX}{i:03}", first_name=f"Load{i:03}", last_name=f"Check{i:03}",
                     gender=Gender.MALE if i % 2 else Gender.FEMALE)
            u.set_unusable_password()
            users.append(u)
        User.objects.bulk_create(users, batch_size=500)
        users = list(User.objects.filter(username__startswith=PREFIX, is_staff=False).order_by("username"))
        Player.objects.bulk_create(
            [Player(user=u, first_name=u.first_name, last_name=u.last_name, gender=u.gender) for u in users],
            batch_size=500,
        )
        return admin

    def players(self):
        return list(Player.objects.filter(user__username__startswith=PREFIX).order_by("user__username"))

    def new_event(self, kind, **kw):
        return Event.objects.create(
            level=Level.objects.get(name="Intermediate"),
            division=Division.objects.get(kind=kind),
            location="Waco Regional Tennis and Fitness Center",
            start_date=datetime.date.today(), end_date=datetime.date.today(),
            court_count=8, games_per_match=1, max_participants=500, **kw,
        )

    def score(self, match, admin):
        loser = self.rng.randint(0, 9)
        games = [(11, loser)] if self.rng.random() < 0.5 else [(loser, 11)]
        scoring.admin_set_score(match, games, admin)

    # --- Events ------------------------------------------------------------

    def run_doubles(self, admin, count):
        team_count = count // 2
        event = self.new_event(Division.Kind.MIXED, title=f"{TITLE} Mixed doubles", team_count=team_count,
                               pool_size=6, matches_per_team=5, total_matches=team_count * 5 // 2)
        people = self.players()
        men = [p for p in people if p.gender == Gender.MALE]
        women = [p for p in people if p.gender == Gender.FEMALE]
        for man, woman in zip(men, women):
            registration.admin_add(event, man, override=True)
            registration.admin_add(event, woman, override=True)
            teams.admin_build_team(event, [man, woman], override=True)
        scheduling.publish(event, 1, admin)
        scheduling.start_play(event, admin)
        for m in event.matches.filter(stage=Match.Stage.ROUND_ROBIN).order_by("start_time", "court"):
            self.score(m, admin)

        event.refresh_from_db()
        table = standings.table(event)
        advancing = min(16, team_count)
        for group in table.seeding().unresolved_within(advancing):
            brackets.set_tiebreak(event, [row.key for row in group], admin)
        brackets.build(event, advancing, admin)
        self.play_bracket(event, admin)
        return event

    def play_bracket(self, event, admin):
        while True:
            ready = list(event.matches.filter(stage=Match.Stage.BRACKET, side_a__isnull=False,
                                              side_b__isnull=False)
                         .exclude(status=Match.Status.CONFIRMED).order_by("bracket_round", "bracket_slot"))
            if not ready:
                return
            for m in ready:
                self.score(m, admin)

    def run_scramble(self, admin, count):
        event = self.new_event(Division.Kind.SCRAMBLE, title=f"{TITLE} Scramble", scramble_rounds=12)
        for p in self.players()[:count]:
            registration.admin_add(event, p, override=True)
        scheduling.publish(event, 1, admin)
        scheduling.start_play(event, admin)
        for m in event.matches.order_by("start_time", "court"):
            self.score(m, admin)
        return event

    def chat(self, event, count):
        people = [p.user for p in self.players()[:20]]
        for i in range(count):
            chat.post(event, people[i % len(people)], f"Load check message {i + 1}. See you on court!")

    # --- Pages -------------------------------------------------------------

    def time_pages(self, admin, doubles, scramble):
        player = doubles.sides.filter(slot=1).first().players.first().user
        scrambler = scramble.registrations.first().player.user
        pages = []
        for event, who in ((doubles, player), (scramble, scrambler)):
            pk = event.pk
            code = event.spectator_code
            pages += [
                (admin, reverse("events:manage_event", args=[pk])),
                (admin, reverse("scheduling:schedule", args=[pk])),
                (admin, reverse("standings:standings", args=[pk])),
                (who, reverse("events:event_detail", args=[pk])),
                (who, reverse("events:event_rounds", args=[pk])),
                (who, reverse("events:event_standings", args=[pk])),
                (who, reverse("chat:room", args=[pk])),
                (None, reverse("events:watch", args=[code])),
                (None, reverse("events:watch_standings", args=[code])),
            ]
            if not event.is_scramble:
                pages += [
                    (admin, reverse("brackets:bracket", args=[pk])),
                    (who, reverse("events:event_bracket", args=[pk])),
                    (who, reverse("chat:poll", args=[pk])),
                    (None, reverse("events:watch_bracket", args=[code])),
                ]
        pages.append((player, reverse("core:home")))

        self.stdout.write(f"\n{'Page':<46} {'Who':<10} {'Time':>7} {'Queries':>8}")
        with override_settings(ALLOWED_HOSTS=["*"], SECURE_SSL_REDIRECT=False):
            for who, url in pages:
                client = Client()
                if who:
                    client.force_login(who)
                connection.queries_log.clear()  # The log only holds 9,000 rows.
                start = time.perf_counter()
                with CaptureQueriesContext(connection) as q:
                    status = client.get(url, secure=True).status_code
                ms = (time.perf_counter() - start) * 1000
                label = "spectator" if who is None else ("admin" if who.is_staff else "player")
                line = f"{url:<46} {label:<10} {ms:6.0f}ms {len(q):>8}"
                if status != 200:
                    self.problems.append(f"{url} answered {status}")
                    line += f"  (status {status})"
                if len(q) > QUERY_BUDGET:
                    self.problems.append(f"{url} as {label}: {len(q)} queries")
                self.stdout.write(self.style.WARNING(line) if status != 200 or len(q) > QUERY_BUDGET else line)
