#!/usr/bin/env bash
# =============================================================================
#  entrypoint.sh — старт web-сервиса:
#    1) дождаться готовности PostgreSQL,
#    2) применить миграции,
#    3) exec gunicorn (PID 1 -> корректная обработка сигналов).
# =============================================================================
set -euo pipefail

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo "[entrypoint] waiting for postgres at ${DB_HOST}:${DB_PORT} ..."
# Ждём TCP-доступности БД через python (без зависимости от nc/pg_isready).
until python -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${DB_HOST}', ${DB_PORT}))
except OSError:
    sys.exit(1)
finally:
    s.close()
" 2>/dev/null; do
    echo "[entrypoint] postgres not ready, retrying in 1s ..."
    sleep 1
done
echo "[entrypoint] postgres is up."

echo "[entrypoint] applying migrations ..."
python manage.py migrate --noinput

echo "[entrypoint] starting gunicorn ..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
