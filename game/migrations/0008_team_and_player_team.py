import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0007_delete_ratelimitbucket'),
    ]

    operations = [
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='nome')),
                ('photo_url', models.URLField(blank=True, max_length=4096, verbose_name='URL da foto')),
            ],
            options={
                'verbose_name': 'equipe',
                'verbose_name_plural': 'equipes',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='player',
            name='team',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='players', to='game.team', verbose_name='equipe atual'),
        ),
    ]
