"""Seed the three Levels and four Divisions (CLAUDE.md section 2)."""

from django.db import migrations

LEVELS = ["Beginner", "Intermediate", "Advanced"]
DIVISIONS = [
    ("Men's", "MENS"),
    ("Women's", "WOMENS"),
    ("Mixed", "MIXED"),
    ("Scramble", "SCRAMBLE"),
]


def seed(apps, schema_editor):
    Level = apps.get_model("events", "Level")
    Division = apps.get_model("events", "Division")
    for order, name in enumerate(LEVELS):
        Level.objects.update_or_create(name=name, defaults={"sort_order": order})
    for order, (name, kind) in enumerate(DIVISIONS):
        Division.objects.update_or_create(name=name, defaults={"kind": kind, "sort_order": order})


def unseed(apps, schema_editor):
    apps.get_model("events", "Level").objects.filter(name__in=LEVELS).delete()
    apps.get_model("events", "Division").objects.filter(name__in=[n for n, _ in DIVISIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("events", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
