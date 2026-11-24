"""Entering, confirming, and fixing scores (section 7). Rules live in rules.py."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import audit
from scheduling.models import Match

from . import rules
from .models import Game, ScoreSubmission
from .rules import GameRules

Status = ScoreSubmission.Status
OPEN_STATUSES = (Status.PENDING, Status.DISPUTED)


class ScoreError(Exception):
    """A friendly message explaining why the score can't be saved."""


# --- Who can do what -------------------------------------------------------

def player_side(match: Match, player) -> str | None:
    """'A' or 'B' if this player is in the match."""
    # .all() uses prefetched players when the caller loaded them.
    if match.side_a_id and any(p.pk == player.pk for p in match.side_a.players.all()):
        return rules.A
    if match.side_b_id and any(p.pk == player.pk for p in match.side_b.players.all()):
        return rules.B
    return None


def match_day(match: Match) -> datetime.date:
    return timezone.localtime(match.start_time, rules.CENTRAL).date()


def lock_time(match: Match) -> datetime.datetime:
    return rules.lock_deadline(match_day(match))


def is_locked(match: Match, now: datetime.datetime | None = None) -> bool:
    return (now or timezone.now()) >= lock_time(match)


def _play_problem(match: Match) -> str | None:
    if not match.event.schedule_locked:
        return "Scores open once the organizer starts play."
    if not match.is_ready:
        return "This match is waiting for its teams. Earlier bracket matches decide who plays."
    return None


def entry_problem(match: Match, player, now=None) -> str | None:
    """Why this player can't enter or confirm a score right now, or None."""
    if not match.event.players_enter_scores:
        return "The organizer enters the scores for this event."
    if player is None or player_side(match, player) is None:
        return "Only players in this match can enter its score."
    problem = _play_problem(match)
    if problem:
        return problem
    if is_locked(match, now):
        return "Score entry closed at midnight after the match day. Ask an organizer to fix it."
    return None


def _check_games(match: Match, games) -> list[rules.Game]:
    games = [(int(a), int(b)) for a, b in games]
    problem = rules.match_problem(games, GameRules.from_event(match.event))
    if problem:
        raise ScoreError(problem)
    return games


def _lock(match: Match) -> Match:
    return Match.objects.select_for_update(of=("self",)).select_related("event", "side_a", "side_b", "round").get(pk=match.pk)


def _final_text(match: Match) -> str:
    games = list(match.games.values_list("side_a_points", "side_b_points"))
    text = rules.score_text(games) if games else "no score"
    return f"{text} (forfeit)" if match.forfeit else text


def _finalize(match: Match, games, *, forfeit: bool = False) -> None:
    match.games.all().delete()
    Game.objects.bulk_create(
        Game(match=match, number=i, side_a_points=a, side_b_points=b) for i, (a, b) in enumerate(games, start=1)
    )
    match.status = Match.Status.CONFIRMED
    match.winner = rules.match_winner(games)
    match.forfeit = forfeit
    match.save(update_fields=["status", "winner", "forfeit"])
    _bracket_hook("after_result", match)


def _bracket_hook(name: str, match: Match) -> None:
    """Bracket matches send their winner on. A blocked move undoes the whole change."""
    from brackets import services as brackets
    from brackets.brackets import BracketError

    try:
        getattr(brackets, name)(match)
    except BracketError as exc:
        raise ScoreError(str(exc)) from exc


def _close_open_submissions(match: Match, status=Status.RESOLVED) -> None:
    match.submissions.filter(status__in=OPEN_STATUSES).update(status=status, decided_at=timezone.now())


# --- Players ---------------------------------------------------------------

@transaction.atomic
def submit(match: Match, player, games, now=None) -> ScoreSubmission:
    """A player enters the score. The other side confirms, or enters theirs.

    If both sides have entered the same score, it's final. If they differ,
    the match is flagged for an admin.
    """
    match = _lock(match)
    problem = entry_problem(match, player, now)
    if problem:
        raise ScoreError(problem)
    games = _check_games(match, games)
    side = player_side(match, player)
    other_side = rules.B if side == rules.A else rules.A

    match.submissions.filter(side=side, status__in=OPEN_STATUSES).update(status=Status.SUPERSEDED)
    theirs = match.submissions.filter(side=other_side, status__in=OPEN_STATUSES).first()
    mine = ScoreSubmission.objects.create(match=match, side=side, games=[list(g) for g in games],
                                          submitted_by=player)
    old = _final_text(match)

    if theirs and theirs.game_list == games:
        _confirm(match, theirs, mine, player)
        audit.log(player.user, "score confirmed", match, old=old, new=rules.score_text(games), event=match.event)
    elif theirs:
        ScoreSubmission.objects.filter(pk__in=[theirs.pk, mine.pk]).update(status=Status.DISPUTED)
        mine.status = Status.DISPUTED
        match.status = Match.Status.DISPUTED
        match.save(update_fields=["status"])
        audit.log(player.user, "score disputed", match, old=theirs.score, new=mine.score, event=match.event)
    else:
        match.status = Match.Status.PENDING
        match.save(update_fields=["status"])
        audit.log(player.user, "score entered", match, old=old, new=mine.score, event=match.event)
    return mine


@transaction.atomic
def confirm(submission: ScoreSubmission, player, now=None) -> None:
    """The other side agrees with a score that was entered."""
    match = _lock(submission.match)
    submission.refresh_from_db()
    problem = entry_problem(match, player, now)
    if problem:
        raise ScoreError(problem)
    if submission.status != Status.PENDING:
        raise ScoreError("That score isn't waiting for confirmation anymore.")
    if player_side(match, player) == submission.side:
        raise ScoreError("The other side needs to confirm this score.")
    old = _final_text(match)
    _confirm(match, submission, None, player)
    audit.log(player.user, "score confirmed", match, old=old, new=submission.score, event=match.event)


def _confirm(match, submission, also, player) -> None:
    now = timezone.now()
    ids = [submission.pk] + ([also.pk] if also else [])
    ScoreSubmission.objects.filter(pk__in=ids).update(status=Status.CONFIRMED, confirmed_by=player, decided_at=now)
    if also:
        also.status = Status.CONFIRMED
    _finalize(match, submission.game_list)


# --- Admins ----------------------------------------------------------------

@transaction.atomic
def admin_set_score(match: Match, games, actor) -> None:
    """Admins can always set a score. Every change is logged."""
    match = _lock(match)
    problem = _play_problem(match)
    if problem:
        raise ScoreError(problem)
    games = _check_games(match, games)
    old = _final_text(match)
    _finalize(match, games)
    _close_open_submissions(match)
    audit.log(actor, "score set by admin", match, old=old, new=rules.score_text(games), event=match.event)


@transaction.atomic
def admin_clear_score(match: Match, actor) -> None:
    """Back to not played. Any entries waiting on it are closed."""
    match = _lock(match)
    old = _final_text(match)
    match.games.all().delete()
    match.status = Match.Status.SCHEDULED
    match.winner = ""
    match.forfeit = False
    match.save(update_fields=["status", "winner", "forfeit"])
    _close_open_submissions(match)
    _bracket_hook("after_clear", match)
    audit.log(actor, "score cleared", match, old=old, new="no score", event=match.event)


@transaction.atomic
def forfeit(match: Match, losing_side: str, actor) -> None:
    """One side forfeits. ASSUMED: the winner gets the forfeit score, 11 to 0 per game by default."""
    if losing_side not in (rules.A, rules.B):
        raise ScoreError("Pick which side forfeits.")
    match = _lock(match)
    problem = _play_problem(match)
    if problem:
        raise ScoreError(problem)
    event = match.event
    winner = rules.B if losing_side == rules.A else rules.A
    games = rules.forfeit_games(winner, GameRules.from_event(event), event.forfeit_points)
    old = _final_text(match)
    _finalize(match, games, forfeit=True)
    _close_open_submissions(match)
    loser = match.side_a if losing_side == rules.A else match.side_b
    audit.log(actor, "forfeit", match, old=old, new=f"{loser.name} forfeits, {rules.score_text(games)}", event=event)


@transaction.atomic
def withdraw(side, actor) -> int:
    """A team withdraws. Every match they haven't finished becomes a forfeit loss."""
    if not side.event.schedule_locked:
        raise ScoreError("Play hasn't started. Remove or split up the team instead.")
    matches = (Match.objects.filter(Q(side_a=side) | Q(side_b=side))
               .filter(side_a__isnull=False, side_b__isnull=False)  # bracket matches still waiting are skipped
               .exclude(status=Match.Status.CONFIRMED))
    count = 0
    for match in matches.select_related("event", "side_a", "side_b"):
        forfeit(match, match.side_letter(side), actor)
        count += 1
    audit.log(actor, "team withdrawn", side, new=f"{count} matches forfeited", event=side.event)
    return count


# --- What a player sees on their match list -------------------------------

@dataclass
class PlayerView:
    side: str | None
    label: str
    action: str  # "enter", "confirm", "change", or ""
    waiting: ScoreSubmission | None = None  # the other side's entry to confirm


def player_view(match: Match, player, now=None) -> PlayerView:
    side = player_side(match, player)
    problem = entry_problem(match, player, now)
    open_subs = [s for s in match.submissions.all() if s.status in OPEN_STATUSES]
    theirs = next((s for s in open_subs if s.side != side), None)
    mine = next((s for s in open_subs if s.side == side), None)
    can_enter = problem is None

    if match.status == Match.Status.DISPUTED:
        return PlayerView(side, "The scores don't match. An organizer will sort it out.", "change" if can_enter else "")
    if match.status == Match.Status.CONFIRMED and not open_subs:
        label = f"Final: {match.score}" + (" (forfeit)" if match.forfeit else "")
        return PlayerView(side, label, "change" if can_enter else "")
    if theirs:
        return PlayerView(side, f"Your opponent entered {theirs.score}. Is that right?",
                          "confirm" if can_enter else "", waiting=theirs)
    if mine:
        return PlayerView(side, f"You entered {mine.score}. Waiting for your opponent to confirm.",
                          "change" if can_enter else "")
    if can_enter:
        return PlayerView(side, "No score yet.", "enter")
    return PlayerView(side, problem or "No score yet.", "")
