# =============================================================================
#  Makefile — служебные команды проекта.
# =============================================================================

.PHONY: migrate test lint

migrate:
	python manage.py migrate --noinput

# Локальный прогон без Postgres: USE_SQLITE=1. В CI БД задаётся через окружение.
test:
	USE_SQLITE=1 DJANGO_SECRET_KEY=test pytest

lint:
	ruff check . && mypy .
