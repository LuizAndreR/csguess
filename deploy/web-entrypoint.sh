#!/bin/sh
set -eu

# Uma vez por container, antes de iniciar o processo master do Gunicorn.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
if ! python manage.py ensure_daily_challenge; then
    printf '%s\n' 'Desafio ainda indisponível; consulte os erros acima e a rotina diária de recuperação.' >&2
fi
exec "$@"
