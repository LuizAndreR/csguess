from django.shortcuts import render
from datetime import date
from functools import wraps
import json
import logging
import re

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.cache import patch_vary_headers

from .models import DailyChallenge, Player
from .progress import read_progress, write_progress
from .normalization import search_key
from .services import compare, eligible_players, local_date, next_rollover


def health(request):
    if request.method != "GET":
        return error("method_not_allowed", "Use GET.", 405)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        response = JsonResponse({"status": "unavailable"}, status=503)
    else:
        response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@ensure_csrf_cookie
def home(request):
    return render(request, "game/classic.html")


logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def error(code, message, status):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


# Padroniza os erros das rotas JSON sem expor detalhes do banco.
def endpoint(method):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method != method:
                response = error("method_not_allowed", f"Use {method}.", 405)
                response["Allow"] = method
                response["Cache-Control"] = "no-store"
                return response

            try:
                response = view(request, *args, **kwargs)
            except APIError as exc:
                response = error(exc.code, exc.message, exc.status)
            except DatabaseError:
                logger.error("Falha de banco na API clássica")
                response = error(
                    "temporarily_unavailable",
                    "Serviço temporariamente indisponível. Tente novamente.",
                    503
                )

            response["Cache-Control"] = "no-store"
            patch_vary_headers(response, ("Cookie",))
            return response

        return wrapped

    return decorate


# Consulta o desafio pronto. A criação acontece apenas no comando diário.
def current_challenge():
    challenge = DailyChallenge.objects.filter(date=local_date()).first()
    if not challenge:
        raise APIError(
            "challenge_unavailable",
            "O desafio de hoje ainda não está disponível. Tente novamente em instantes.",
            503
        )
    return challenge


def guess_result(chosen, challenge, number):
    won = chosen["id"] == challenge.secret_player_id
    return {
        "player": chosen,
        "comparison": compare(chosen, challenge.secret_snapshot),
        "number": number,
        "correct": won,
        "state": "completed" if won else "in_progress"
    }


def victory(challenge, players):
    if challenge.secret_player_id in players:
        return {"player": challenge.secret_snapshot, "attempts": len(players)}
    return None


@ensure_csrf_cookie
@endpoint("GET")
def classic(request):
    challenge = current_challenge()
    players = read_progress(request, challenge)
    initialize = players is None
    players = players or []

    # Reconstitui as tentativas com os dados atuais do cadastro.
    current_players = {
        player.pk: data
        for player, data in eligible_players(Player.objects.filter(pk__in=players))
    }
    results = [
        guess_result(current_players[player_id], challenge, number)
        for number, player_id in enumerate(players, 1)
        if player_id in current_players
    ]
    summary = victory(challenge, players)
    payload = {
        "challenge_date": challenge.date.isoformat(),
        "challenge_id": str(challenge.public_id),
        "next_rollover": next_rollover(challenge.date),
        "state": "completed" if summary else "in_progress",
        "guesses": results
    }

    # O secreto só é devolvido se os IDs assinados incluem uma tentativa correta.
    if summary:
        payload["victory"] = summary

    response = JsonResponse(payload)
    if initialize:
        write_progress(response, request, challenge, [])
    return response


@endpoint("GET")
def player_search(request):
    query = request.GET.get("q", "")
    if len(query) > 100:
        raise APIError("invalid_query", "Informe entre 2 e 100 caracteres para buscar.")

    key = search_key(query)
    if len(key) < 2:
        raise APIError("invalid_query", "Informe entre 2 e 100 caracteres para buscar.")

    challenge = current_challenge()
    results = []

    # O histórico vem do cookie assinado deste navegador, sem consulta a partidas.
    players = read_progress(request, challenge) or []
    roster = Player.objects.exclude(pk__in=players)

    for player, data in eligible_players(roster):
        nick, name = search_key(data["nick"]), search_key(data["name"])
        if key not in nick and key not in name:
            continue

        # Prioridade: exato, início do nick e demais ocorrências.
        priority = 0 if key in (nick, name) else 1 if nick.startswith(key) else 2
        results.append((
            (priority, nick, name, player.pk),
            {
                "id": player.pk,
                "nick": data["nick"],
                "name": data["display_name"],
                "photo_url": data["photo_url"]
            }
        ))

    results.sort(key=lambda item: item[0])
    return JsonResponse({"players": [data for _, data in results[:10]]})


# Valida o formato do POST de tentativa (compartilhado pelos modos Clássico e Logo).
def parse_guess_body(request, field, code):
    if request.content_type != "application/json":
        raise APIError(
            "invalid_content_type",
            "Use Content-Type application/json.",
            415
        )
    if len(request.body) > 4096:
        raise APIError("invalid_body", "Corpo da requisição muito grande.", 413)

    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise APIError("invalid_json", "Envie um objeto JSON válido.")

    if not isinstance(body, dict) or set(body) != {"challenge_date", field}:
        raise APIError("invalid_body", f"Informe challenge_date e {field}.")
    if type(body[field]) is not int or not 0 < body[field] < 2**63:
        raise APIError(code, f"{field} deve ser um inteiro positivo válido.")

    value = body["challenge_date"]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise APIError("invalid_date", "Use challenge_date no formato AAAA-MM-DD.")

    try:
        submitted_date = date.fromisoformat(value)
    except ValueError:
        raise APIError("invalid_date", "Data inválida.")

    if submitted_date != local_date():
        raise APIError(
            "challenge_changed",
            "O dia mudou. Carregue o novo desafio.",
            409
        )
    return body[field], submitted_date


@endpoint("POST")
def guesses(request):
    # Valida o formato da requisição antes de acessar a partida.
    player_id, submitted_date = parse_guess_body(request, "player_id", "invalid_player")
    body = {"player_id": player_id}

    challenge = current_challenge()
    players = read_progress(request, challenge)
    if players is None:
        raise APIError(
            "session_required",
            "Carregue /game/classic/ antes de jogar.",
            409
        )
    if challenge.secret_player_id in players:
        raise APIError("match_completed", "Esta partida já foi concluída.", 409)
    if body["player_id"] in players:
        raise APIError("duplicate_guess", "Este jogador já foi escolhido nesta partida.", 409)

    selected = next(
        eligible_players(Player.objects.filter(pk=body["player_id"])),
        None
    )
    if selected is None:
        raise APIError("invalid_player", "Jogador não disponível para este desafio.")

    player, data = selected
    if submitted_date != local_date():
        raise APIError(
            "challenge_changed",
            "O dia mudou. Carregue o novo desafio em /game/classic/.",
            409
        )

    # As pistas são calculadas no servidor; só os IDs tentados voltam ao cookie.
    players = players + [player.pk]
    result = guess_result(data, challenge, len(players))
    summary = victory(challenge, players)
    if summary:
        result["victory"] = summary

    response = JsonResponse(result, status=201)
    return write_progress(response, request, challenge, players)


def csrf_failure(request, reason=""):
    return error(
        "csrf_failed",
        "Token CSRF ausente ou inválido. Carregue o desafio e envie X-CSRFToken.",
        403
    )
