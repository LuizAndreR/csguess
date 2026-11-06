FROM python:3.12.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 csguess \
    && useradd --uid 10001 --gid csguess --no-create-home csguess

COPY --chown=csguess:csguess . .
RUN mkdir -p /app/staticfiles && chown csguess:csguess /app/staticfiles
USER csguess
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/deploy/web-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "--timeout", "30"]
