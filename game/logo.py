"""Regras do modo Logo: sorteio da equipe do dia e imagem embaçada gerada no servidor.

O logo original nunca sai do servidor: a tela só recebe a versão embaçada do nível
correspondente ao progresso (cookie assinado). Ao acertar, recebe a imagem nítida.
"""
from functools import lru_cache
import hashlib
from io import BytesIO
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

from .models import Team, TeamChallenge
from .services import local_date

logger = logging.getLogger(__name__)

# Lock próprio: o modo Logo não disputa o lock do clássico.
LOGO_CHALLENGE_LOCK = 731946216
COOKIE_NAME = "csguess_logo_progress"
COOKIE_SALT = "game.logo.progress.v1"

# A cada BLUR_STEP tentativas o raio do desfoque passa para o próximo valor da lista.
BLUR_STEP = 10
BLUR_RADII = (26, 15, 7, 0)
CANVAS = (480, 300)
PADDING = 36
BACKGROUND = (26, 32, 41)


class NoEligibleTeams(Exception):
    pass


def logo_path(team):
    """Arquivo local do logo, nomeado pelo hash da photo_url.

    Independe do ID da equipe: recriar o banco ou trocar a URL nunca aponta para o arquivo errado.
    """
    digest = hashlib.sha256(team.photo_url.encode()).hexdigest()[:20]
    return Path(settings.TEAM_LOGO_DIR) / f"{digest}.png"


# Só participam equipes com foto cadastrada e o arquivo local já baixado.
def eligible_teams(queryset=None):
    if queryset is None:
        queryset = Team.objects.all()
    return [team for team in queryset.exclude(photo_url="").order_by("pk") if logo_path(team).is_file()]


def blur_index(attempts, solved=False):
    """0 = mais embaçado; o último índice é a imagem nítida."""
    last = len(BLUR_RADII) - 1
    return last if solved else min(attempts // BLUR_STEP, last)


def attempts_to_next_level(attempts, index):
    return None if index >= len(BLUR_RADII) - 1 else BLUR_STEP - attempts % BLUR_STEP


@lru_cache(maxsize=256)
def _render(path, mtime_ns, index):
    from PIL import Image, ImageFilter

    with Image.open(path) as source:
        logo = source.convert("RGBA")
    logo.thumbnail((CANVAS[0] - 2 * PADDING, CANVAS[1] - 2 * PADDING), Image.LANCZOS)
    canvas = Image.new("RGBA", CANVAS, BACKGROUND + (255,))
    canvas.alpha_composite(logo, ((CANVAS[0] - logo.width) // 2, (CANVAS[1] - logo.height) // 2))
    radius = BLUR_RADII[index]
    if radius:
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
    output = BytesIO()
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output.getvalue()


def render_logo(team, index):
    path = logo_path(team)
    return _render(str(path), path.stat().st_mtime_ns, index)


@transaction.atomic
def ensure_logo_challenge(date=None):
    date = date or local_date()
    if connection.vendor != "postgresql":
        raise RuntimeError("Sorteio exige PostgreSQL para serialização transacional")

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOGO_CHALLENGE_LOCK])

    existing = TeamChallenge.objects.filter(date=date).first()
    if existing:
        return existing

    # Mesma regra do clássico: a equipe não se repete entre D−6 e D+6.
    blocked = set(TeamChallenge.objects.filter(
        date__range=(date - timedelta(days=6), date + timedelta(days=6))
    ).values_list("secret_team_id", flat=True))
    candidates = [team for team in eligible_teams() if team.pk not in blocked]
    if not candidates:
        logger.error("Desafio de logo indisponível em %s: nenhuma equipe elegível", date)
        raise NoEligibleTeams(
            "Nenhuma equipe elegível (com foto e arquivo local) respeita o bloqueio de sete dias; "
            "rode fetch_team_logos e revise o histórico."
        )

    import secrets
    return TeamChallenge.objects.create(date=date, secret_team=secrets.choice(candidates))
