"""Progresso do clássico guardado somente no cookie do navegador."""
from django.core import signing

COOKIE_NAME = "csguess_classic_progress"
COOKIE_SALT = "game.classic.progress.v1"
COOKIE_MAX_AGE = 14 * 24 * 60 * 60


def read_progress(request, challenge):
    value = request.COOKIES.get(COOKIE_NAME)
    if not value:
        return None

    try:
        progress = signing.loads(value, salt=COOKIE_SALT, max_age=COOKIE_MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return None

    if not isinstance(progress, dict) or progress.get("challenge") != str(challenge.public_id):
        return None

    players = progress.get("players")
    if not isinstance(players, list) or any(type(player_id) is not int for player_id in players):
        return None
    if len(players) != len(set(players)):
        return None

    return players


def write_progress(response, request, challenge, players):
    # O cookie contém apenas o desafio público e os IDs já tentados, nunca a resposta.
    value = signing.dumps(
        {"challenge": str(challenge.public_id), "players": players},
        salt=COOKIE_SALT,
        compress=True
    )
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=request.is_secure(),
        samesite="Lax"
    )
    return response
