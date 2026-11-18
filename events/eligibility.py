"""Gender eligibility for divisions (section 3).

Gender is used only here. Each function returns a friendly problem message,
or None when everything is fine. Admins can override.
"""

from accounts.models import Gender

from .models import Division

Kind = Division.Kind


def registration_problem(division: Division, player) -> str | None:
    """Can this player sign up for an event in this division?"""
    if division.kind in (Kind.MENS, Kind.WOMENS) and not player.gender:
        return "Add your gender to your profile before joining this event."
    if division.kind == Kind.MENS and player.gender != Gender.MALE:
        return "This is a men's event."
    if division.kind == Kind.WOMENS and player.gender != Gender.FEMALE:
        return "This is a women's event."
    # Mixed: anyone can register. The team itself must be one male and one female.
    return None


def team_problem(division: Division, players) -> str | None:
    """Is this a valid pair of partners for this division?"""
    players = list(players)
    if division.kind == Kind.SCRAMBLE:
        return "Scramble events don't use fixed teams."
    if len(players) != 2:
        return "A team needs exactly two players."
    if players[0].pk is not None and players[0].pk == players[1].pk:
        return "A team needs two different players."

    genders = sorted(p.gender for p in players)
    if division.kind == Kind.MENS and genders != [Gender.MALE, Gender.MALE]:
        return "Men's teams need two male players."
    if division.kind == Kind.WOMENS and genders != [Gender.FEMALE, Gender.FEMALE]:
        return "Women's teams need two female players."
    if division.kind == Kind.MIXED and genders != sorted([Gender.MALE, Gender.FEMALE]):
        return "Mixed teams need one male and one female player."
    return None


def partner_problem(division: Division, player, partner) -> str | None:
    """Would `partner` be a valid partner for `player`? Used before the team is full."""
    return team_problem(division, [player, partner])
