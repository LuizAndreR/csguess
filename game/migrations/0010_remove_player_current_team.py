from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0009_copy_current_team_to_team'),
    ]

    operations = [
        migrations.RemoveField(model_name='player', name='current_team'),
    ]
