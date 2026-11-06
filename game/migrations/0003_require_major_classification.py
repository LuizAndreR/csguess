from django.db import migrations, models


def require_classification(apps, schema_editor):
    Player = apps.get_model("game", "Player")
    if Player.objects.using(schema_editor.connection.alias).filter(is_major_winner__isnull=True).exists():
        raise RuntimeError(
            "Existem jogadores sem apuração de Major. Importe o contrato v2 após a migração 0002 "
            "antes de aplicar 0003. Não preencher False por suposição."
        )


class Migration(migrations.Migration):
    dependencies = [("game", "0002_player_is_major_winner")]
    operations = [
        migrations.RunPython(require_classification, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="player", name="is_major_winner",
            field=models.BooleanField("campeão de Major como jogador"),
        ),
    ]
