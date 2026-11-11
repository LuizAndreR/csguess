#!/bin/sh
set -eu

# Uma vez por container, antes de iniciar o processo master do Gunicorn.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# Baixa só os logos que faltam; falha de rede não impede o site de subir.
if ! python manage.py fetch_team_logos; then
    printf '%s\n' 'Falha ao baixar logos; o modo Logo usa só os já baixados.' >&2
fi
if ! python manage.py ensure_daily_challenge; then
    printf '%s\n' 'Desafio ainda indisponível; consulte os erros acima e a rotina diária de recuperação.' >&2
fi
exec "$@"
