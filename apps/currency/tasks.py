"""Celery-таски курсов валют.

Идемпотентны: запись через update_or_create по (code, rate_date) — повторный
прогон/ретрай не плодит дублей.
"""

from __future__ import annotations

import datetime as dt
import logging

from celery import shared_task
from django.utils import timezone

from apps.integrations.currency.base import IntegrationError
from apps.integrations.currency.registry import get_currency_provider

from .models import CurrencyRate

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(IntegrationError,),  # ретраим только сетевые сбои, не ошибки БД
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_currency_rates(self, date_iso: str | None = None) -> int:
    """Загрузить курсы НБУ на указанную дату (или сегодня) и сохранить.

    Возвращает число сохранённых/обновлённых курсов.
    """
    on_date = dt.date.fromisoformat(date_iso) if date_iso else timezone.localdate()
    rates = get_currency_provider().get_rates(on_date)
    if not rates:
        # НБУ не публикует курс на выходной/праздник — это нормально, не ошибка.
        logger.info("Курсы на %s отсутствуют (вероятно, выходной)", on_date)
        return 0

    saved = 0
    for dto in rates:
        CurrencyRate.objects.update_or_create(
            code=dto.code,
            rate_date=dto.rate_date,
            defaults={"rate_uah": dto.rate_uah},
        )
        saved += 1
    logger.info("Сохранено курсов на %s: %d", on_date, saved)
    return saved


@shared_task
def backfill_currency_rates(days: int = 30) -> int:
    """Догрузить ИСТОРИЧЕСКИЕ курсы за последние `days` дней.

    Нужно, потому что beat тянет только «сегодня», а график истории конвертируется
    курсом своей даты — без бэкфилла прошлые даты пересчитывались бы неверно
    (carry-forward от старта сервиса). Идемпотентно: дни с уже загруженным курсом
    пропускаем (не дёргаем НБУ зря).
    """
    today = timezone.localdate()
    have_days = set(
        CurrencyRate.objects.filter(
            rate_date__gte=today - dt.timedelta(days=days)
        ).values_list("rate_date", flat=True)
    )
    total = 0
    for delta in range(days):
        day = today - dt.timedelta(days=delta)
        if day in have_days:
            continue
        # Сбой НБУ на одном дне не должен оборвать догон остальных: .run() идёт
        # синхронно мимо autoretry, поэтому ловим IntegrationError здесь сами.
        try:
            total += fetch_currency_rates.run(date_iso=day.isoformat())
        except IntegrationError:
            logger.warning("backfill: курс на %s недоступен — пропуск дня", day)
    return total
