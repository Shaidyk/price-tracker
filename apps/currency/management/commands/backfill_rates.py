"""Догрузить исторические курсы НБУ за N дней.

Запускать при первом деплое/демо, чтобы график истории конвертировался корректно
по курсу своей даты, а не carry-forward от старта сервиса.
    python manage.py backfill_rates --days 35
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.currency.tasks import backfill_currency_rates


class Command(BaseCommand):
    help = "Загрузить исторические курсы НБУ за последние N дней."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--days", type=int, default=35)

    def handle(self, *args, **options) -> None:
        days = options["days"]
        saved = backfill_currency_rates.run(days=days)
        self.stdout.write(self.style.SUCCESS(f"Догружено курсов за {days} дн.: {saved}"))
