import re

from django.core.exceptions import ValidationError


def validate_nationalities(value):
    if not isinstance(value, list) or any(
        not isinstance(code, str) or not re.fullmatch(r"[A-Za-z]{2}", code)
        for code in value
    ):
        raise ValidationError("Informe uma lista de códigos de país com duas letras, como BR.")
    if len({code.upper() for code in value}) != len(value):
        raise ValidationError("Os códigos de país não podem se repetir.")


def validate_roles(value):
    if not isinstance(value, list) or any(
        not isinstance(
            role,
            str
        ) or role not in {"rifle", "awp", "igl"} for role in value
    ):
        raise ValidationError("Informe funções restritas a rifle, awp e igl.")
    if len(set(value)) != len(value):
        raise ValidationError("As funções não podem se repetir.")
