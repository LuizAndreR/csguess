from django.db import migrations

NO_TEAM = "No team"


def copy_forward(apps, schema_editor):
    Player = apps.get_model("game", "Player")
    Team = apps.get_model("game", "Team")
    teams = {}
    for player in Player.objects.order_by("pk"):
        name = (player.current_team or "").strip()
        if not name or name == NO_TEAM:
            continue
        if name not in teams:
            teams[name], _ = Team.objects.get_or_create(name=name)
        player.team = teams[name]
        player.save(update_fields=["team"])


def copy_back(apps, schema_editor):
    Player = apps.get_model("game", "Player")
    for player in Player.objects.select_related("team"):
        player.current_team = player.team.name if player.team_id else NO_TEAM
        player.save(update_fields=["current_team"])


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0008_team_and_player_team'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
    ]
