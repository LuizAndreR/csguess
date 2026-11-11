"""API e página do modo Logo. O progresso fica em cookie assinado próprio."""
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .logo import (
    COOKIE_NAME, COOKIE_SALT, attempts_to_next_level, blur_index, eligible_teams, render_logo,
)
from .models import TeamChallenge
from .normalization import search_key
from .progress import read_progress, write_progress
from .services import local_date, next_rollover
from .views import APIError, endpoint, parse_guess_body


@ensure_csrf_cookie
def page(request):
    return render(request, "game/logo.html")


def current_challenge():
    challenge = TeamChallenge.objects.select_related("secret_team").filter(date=local_date()).first()
    if not challenge:
        raise APIError(
            "challenge_unavailable",
            "O desafio de hoje ainda não está disponível. Tente novamente em instantes.",
            503
        )
    return challenge


def progress(request, challenge):
    return read_progress(request, challenge, COOKIE_NAME, COOKIE_SALT)


def save(response, request, challenge, teams):
    return write_progress(response, request, challenge, teams, COOKIE_NAME, COOKIE_SALT)


def public_team(team):
    # Nunca inclui a foto: o logo só sai embaçado pelo endpoint de imagem.
    return {"id": team.pk, "name": team.name}


def image_state(challenge, teams):
    solved = challenge.secret_team_id in teams
    index = blur_index(len(teams), solved)
    return {
        "attempts": len(teams),
        "blur_level": index,
        "attempts_to_next_level": attempts_to_next_level(len(teams), index),
        "image_url": f"/game/logo/image/?v={index}-{challenge.public_id}",
    }


def guess_result(team, challenge, number):
    return {
        "team": public_team(team),
        "number": number,
        "correct": team.pk == challenge.secret_team_id
    }


@ensure_csrf_cookie
@endpoint("GET")
def state(request):
    challenge = current_challenge()
    teams = progress(request, challenge)
    initialize = teams is None
    teams = teams or []

    known = {team.pk: team for team in eligible_teams()}
    secret = challenge.secret_team
    known.setdefault(secret.pk, secret)
    solved = secret.pk in teams
    payload = {
        "challenge_date": challenge.date.isoformat(),
        "challenge_id": str(challenge.public_id),
        "next_rollover": next_rollover(challenge.date),
        "state": "completed" if solved else "in_progress",
        "guesses": [
            guess_result(known[team_id], challenge, number)
            for number, team_id in enumerate(teams, 1) if team_id in known
        ],
        **image_state(challenge, teams),
    }
    if solved:
        payload["victory"] = {"team": public_team(secret), "attempts": len(teams)}

    response = JsonResponse(payload)
    if initialize:
        save(response, request, challenge, [])
    return response


@endpoint("GET")
def image(request):
    challenge = current_challenge()
    teams = progress(request, challenge) or []
    index = blur_index(len(teams), challenge.secret_team_id in teams)
    try:
        content = render_logo(challenge.secret_team, index)
    except OSError:
        raise APIError("image_unavailable", "Imagem indisponível no momento.", 503)
    return HttpResponse(content, content_type="image/png")


@endpoint("GET")
def team_search(request):
    query = request.GET.get("q", "")
    if len(query) > 100:
        raise APIError("invalid_query", "Informe entre 2 e 100 caracteres para buscar.")
    key = search_key(query)
    if len(key) < 2:
        raise APIError("invalid_query", "Informe entre 2 e 100 caracteres para buscar.")

    challenge = current_challenge()
    already = set(progress(request, challenge) or [])
    results = []
    for team in eligible_teams():
        name = search_key(team.name)
        if team.pk in already or key not in name:
            continue
        priority = 0 if key == name else 1 if name.startswith(key) else 2
        results.append(((priority, name, team.pk), public_team(team)))

    results.sort(key=lambda item: item[0])
    return JsonResponse({"teams": [data for _, data in results[:10]]})


@endpoint("POST")
def guesses(request):
    team_id, _ = parse_guess_body(request, "team_id", "invalid_team")

    challenge = current_challenge()
    teams = progress(request, challenge)
    if teams is None:
        raise APIError("session_required", "Carregue /logo/ antes de jogar.", 409)
    if challenge.secret_team_id in teams:
        raise APIError("match_completed", "Esta partida já foi concluída.", 409)
    if team_id in teams:
        raise APIError("duplicate_guess", "Esta equipe já foi escolhida nesta partida.", 409)

    chosen = next((team for team in eligible_teams() if team.pk == team_id), None)
    if chosen is None:
        raise APIError("invalid_team", "Equipe não disponível para este desafio.")

    teams = teams + [chosen.pk]
    result = {**guess_result(chosen, challenge, len(teams)), **image_state(challenge, teams)}
    result["state"] = "completed" if result["correct"] else "in_progress"
    if result["correct"]:
        result["victory"] = {"team": public_team(chosen), "attempts": len(teams)}

    response = JsonResponse(result, status=201)
    return save(response, request, challenge, teams)
