# =============================================================================
#  Dockerfile — единый образ для web / worker / beat.
#  Python 3.12-slim + libpq (рантайм psycopg).
# =============================================================================
FROM python:3.12-slim

# Не писать .pyc, не буферизовать stdout/stderr (логи сразу видны).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Системные зависимости: libpq5 — рантайм для psycopg (колесо [binary]).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала зависимости — кэш слоёв.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Затем код проекта.
COPY . .

# Непривилегированный пользователь.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# По умолчанию — web-сервис. worker/beat переопределяют command в compose.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
