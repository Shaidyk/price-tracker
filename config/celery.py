"""Celery-приложение и расписание Beat.

Запуск:
    celery -A config worker -l info
    celery -A config beat   -l info
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pricetracker")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Расписание периодических задач.
# Курсы тянем раньше цен — конвертация на сегодня должна иметь свежий курс.
app.conf.beat_schedule = {
    "fetch-currency-rates-daily": {
        "task": "apps.currency.tasks.fetch_currency_rates",
        "schedule": crontab(hour=6, minute=0),
    },
    "fetch-prices-daily": {
        "task": "apps.pricing.tasks.fetch_all_prices",
        "schedule": crontab(hour=6, minute=30),
    },
}
