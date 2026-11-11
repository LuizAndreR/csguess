"""Normalização compartilhada pelo cadastro, importação e jogo."""
import re
import unicodedata


NO_TEAM = "No team"


def normalize_team(value):
    return NO_TEAM if value is None or (isinstance(value, str) and not value.strip()) else value


# Busca sem acentos, maiúsculas ou separadores, tratando o e 0 como equivalentes.
def search_key(value):
    text = unicodedata.normalize("NFKD", value.casefold())
    text = text.replace("0", "o")
    return "".join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def parse_activity(value):
    match = re.fullmatch(r"([0-9]{4}) – ([0-9]{4}|Present)", value)
    if not match:
        raise ValueError("years_active deve usar AAAA – AAAA ou AAAA – Present")

    start = int(match[1])
    # Fim aberto (Present) permanece diferente de um ano numérico.
    end = None if match[2] == "Present" else int(match[2])
    if start < 1900 or (end is not None and (end < start or end > 9999)):
        raise ValueError("years_active contém intervalo inválido")

    return start, end
