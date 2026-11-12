"""Regras do clássico. GETs nunca chamam ensure_daily_challenge."""
from datetime import datetime, time, timedelta
import logging
import secrets
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from .models import DailyChallenge, Player
from .normalization import normalize_team, parse_activity
from .validators import validate_nationalities, validate_roles

logger = logging.getLogger(__name__)
GAME_TZ = ZoneInfo("America/Fortaleza")

# Todos os criadores de desafios devem adquirir este mesmo lock, antes de ler o histórico.
CHALLENGE_LOCK = 731946215


class NoEligiblePlayers(Exception):
    pass


def local_date():
    return timezone.now().astimezone(GAME_TZ).date()


def next_rollover(date):
    return datetime.combine(date + timedelta(days=1), time.min, GAME_TZ).isoformat()


def available_hints(challenge, players):
    # Só contam tentativas aceitas no cookie assinado; um acerto encerra as dicas.
    if challenge.secret_player_id in players:
        return {}

    hints = {}
    if len(players) >= 10:
        hints["nationalities"] = challenge.secret_snapshot["nationalities"]
    if len(players) >= 15:
        hints["current_team"] = normalize_team(challenge.secret_snapshot["current_team"])

    return hints


# Valida e prepara os dados do jogador, sem modificar o cadastro.
def player_snapshot(player):
    validate_nationalities(player.nationalities)
    validate_roles(player.roles)
    if not player.nick.strip() or not player.name.strip():
        raise ValueError("nick e name são obrigatórios")
    if not player.nationalities or not player.roles:
        raise ValueError("nacionalidades e funções são obrigatórias para comparação")
    if player.career_status not in Player.CareerStatus.values:
        raise ValueError("status de carreira inválido")
    if type(player.is_major_winner) is not bool:
        raise ValueError("is_major_winner deve ser booleano")

    team = normalize_team(player.current_team)
    if not isinstance(team, str) or (player.career_status == "retired" and team != "No team"):
        raise ValueError("equipe incompatível com a carreira")

    parse_activity(player.years_active)

    return {
        "id": player.pk,
        "nick": player.nick,
        "name": player.name,
        "display_name": " ".join(player.name.split()[:2]),
        "photo_url": player.photo_url,
        "nationalities": sorted(code.upper() for code in player.nationalities),
        "career_status": player.career_status,
        "current_team": team,
        "roles": sorted(player.roles),
        "is_major_winner": player.is_major_winner,
        "years_active": player.years_active
    }


# A busca, as tentativas e o sorteio usam os mesmos critérios de participação.
def eligible_players(queryset=None):
    if queryset is None:
        queryset = Player.objects.order_by("pk")

    for player in queryset.select_related("team").iterator():
        try:
            data = player_snapshot(player)
        except (ValueError, ValidationError, TypeError, AttributeError) as exc:
            logger.warning("Perfil inelegível: player_id=%s motivo=%s", player.pk, exc)
            continue

        yield player, data


@transaction.atomic
def ensure_daily_challenge(date=None):
    date = date or local_date()
    if connection.vendor != "postgresql":
        raise RuntimeError("Sorteio exige PostgreSQL para serialização transacional")

    # O lock no banco serializa sorteios, inclusive quando as datas são diferentes.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CHALLENGE_LOCK])

    existing = DailyChallenge.objects.filter(date=date).first()
    if existing:
        return existing

    # Simétrico: protege inclusive lacunas anteriores a desafios futuros já gravados.
    blocked = set(DailyChallenge.objects.filter(
        date__range=(date - timedelta(days=6), date + timedelta(days=6))
    ).values_list("secret_player_id", flat=True))

    candidates = [
        (player, data)
        for player, data in eligible_players()
        if player.pk not in blocked
    ]
    if not candidates:
        logger.error(
            "Desafio indisponível em %s: nenhum candidato elegível respeita o bloqueio de sete dias",
            date
        )
        raise NoEligiblePlayers("Nenhum jogador elegível respeita o bloqueio de sete dias; revise os perfis e o histórico.")

    selected, snapshot = secrets.choice(candidates)
    challenge = DailyChallenge.objects.create(
        date=date,
        secret_player=selected,
        secret_snapshot=snapshot
    )

    return challenge


def compare_sets(chosen, secret):
    chosen, secret = set(chosen), set(secret)

    return "correct" if chosen == secret else "partial" if chosen & secret else "incorrect"


def compare_year(chosen, secret):
    if chosen == secret:
        return {"status": "correct", "direction": None}

    # None representa Present; ele não é convertido para o ano atual.
    if secret is None:
        direction = "ongoing"
    elif chosen is None:
        direction = "ended"
    else:
        direction = "up" if secret > chosen else "down"

    return {"status": "incorrect", "direction": direction}


def compare(chosen, secret):
    start, end = parse_activity(chosen["years_active"])
    secret_start, secret_end = parse_activity(secret["years_active"])

    result = {
        field: "correct" if chosen[field] == secret[field] else "incorrect"
        for field in ("career_status", "is_major_winner")
    }

    result["current_team"] = "correct" if normalize_team(chosen["current_team"]) == normalize_team(secret["current_team"]) else "incorrect"
    result["player"] = "correct" if chosen["id"] == secret["id"] else "incorrect"

    for field in ("nationalities", "roles"):
        result[field] = compare_sets(chosen[field], secret[field])

    result["activity"] = {
        "start": compare_year(start, secret_start),
        "end": compare_year(end, secret_end)
    }

    return result
