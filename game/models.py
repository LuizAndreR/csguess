import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .normalization import NO_TEAM
from .validators import validate_nationalities, validate_roles


class Team(models.Model):
    name = models.CharField("nome", max_length=255, unique=True)
    photo_url = models.URLField("URL da foto", max_length=4096, blank=True)

    class Meta:
        verbose_name = "equipe"
        verbose_name_plural = "equipes"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = (self.name or "").strip()
        if self.name.casefold() == NO_TEAM.casefold():
            raise ValidationError({"name": f"“{NO_TEAM}” é reservado; deixe o jogador sem equipe."})

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class Player(models.Model):
    class CareerStatus(models.TextChoices):
        UNKNOWN = "unknown", "Desconhecido"
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        RETIRED = "retired", "Aposentado"

    nick = models.CharField("nick", max_length=150, db_index=True)
    name = models.CharField("nome", max_length=255)
    nationalities = models.JSONField(
        "nacionalidades",
        default=list,
        blank=True,
        validators=[validate_nationalities]
    )
    career_status = models.CharField(
        "status da carreira",
        max_length=16,
        choices=CareerStatus,
        default=CareerStatus.UNKNOWN
    )
    team = models.ForeignKey(
        Team,
        verbose_name="equipe atual",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="players"
    )
    roles = models.JSONField(
        "funções",
        default=list,
        blank=True,
        validators=[validate_roles]
    )
    years_active = models.CharField(
        "período de atividade informado",
        max_length=255,
        blank=True
    )
    is_major_winner = models.BooleanField("campeão de Major como jogador")
    photo_url = models.URLField("URL da foto", max_length=4096, blank=True)

    source = models.CharField("fonte", max_length=150)
    source_id = models.TextField("identificador na fonte")
    source_url = models.URLField("URL original", max_length=4096, blank=True)
    source_collected_at = models.DateTimeField(
        "coletado na origem em",
        null=True,
        blank=True
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "jogador"
        verbose_name_plural = "jogadores"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_id"],
                name="player_source_identity_unique"
            ),
        ]

    def __str__(self):
        return self.nick

    @property
    def current_team(self):
        """Nome da equipe atual; jogador sem equipe retorna "No team"."""
        return self.team.name if self.team_id else NO_TEAM

    def clean(self):
        super().clean()
        errors = {}

        for field in ("years_active", "photo_url", "source_url"):
            if getattr(self, field) is None:
                errors[field] = ["Use uma string vazia para informação ausente."]

        # Validar inclusive valores vazios de tipos incorretos que blank=True ignora.
        for field, validator in (
            ("nationalities", validate_nationalities),
            ("roles", validate_roles)
        ):
            try:
                validator(getattr(self, field))
            except ValidationError as exc:
                errors[field] = exc.messages

        if type(self.is_major_winner) is not bool:
            errors["is_major_winner"] = ["Informe um booleano real."]
        if self.career_status == "retired" and self.team_id is not None:
            errors["team"] = ["Aposentado deve ficar sem equipe."]

        if errors:
            raise ValidationError(errors)

        self.nationalities = [code.upper() for code in self.nationalities]

    def full_clean(self, *args, **kwargs):
        if type(self.is_major_winner) is not bool:
            raise ValidationError({"is_major_winner": "Informe um booleano real."})
        return super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# Um desafio por data: referência ao jogador e cópia fixa da resposta daquele dia.
class DailyChallenge(models.Model):
    date = models.DateField(unique=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    secret_player = models.ForeignKey(Player, on_delete=models.PROTECT)
    secret_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


# Um desafio de logo por data: a equipe secreta é só uma referência (não há snapshot).
class TeamChallenge(models.Model):
    date = models.DateField(unique=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    secret_team = models.ForeignKey(Team, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
