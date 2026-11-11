"""Progresso do clássico guardado somente no cookie do navegador."""
from django.core import signing

COOKIE_NAME = "csguess_classic_progress"
COOKIE_SALT = "game.classic.progress.v1"
COOKIE_MAX_AGE = 14 * 24 * 60 * 60


def read_progress(request, challenge, cookie=COOKIE_NAME, salt=COOKIE_SALT):
    value = request.COOKIES.get(cookie)
    if not value:
        return None

    try:
        progress = signing.loads(value, salt=salt, max_age=COOKIE_MAX_AGE)
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


def write_progress(response, request, challenge, players, cookie=COOKIE_NAME, salt=COOKIE_SALT):
    # O cookie contém apenas o desafio público e os IDs já tentados, nunca a resposta.
    value = signing.dumps(
        {"challenge": str(challenge.public_id), "players": players},
        salt=salt,
        compress=True
    )
    response.set_cookie(
        cookie,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=request.is_secure(),
        samesite="Lax"
    )
    return response
