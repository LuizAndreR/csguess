from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("game", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="player",
            name="is_major_winner",
            field=models.BooleanField("campeão de Major como jogador", null=True),
        ),
    ]
