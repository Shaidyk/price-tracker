"""Курсы валют (НБУ): гривна за 1 единицу валюты, по дням.

Храним историю курсов, потому что историю цен надо пересчитывать курсом ТОГО дня —
это смысл требования «исторические курсы валют».
"""

from __future__ import annotations

from django.db import models


class CurrencyRate(models.Model):
    code = models.CharField(max_length=3, help_text="ISO-код валюты, напр. USD, EUR")
    rate_date = models.DateField()
    # UAH за 1 единицу валюты (как отдаёт НБУ). NUMERIC, не float.
    rate_uah = models.DecimalField(max_digits=18, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code", "rate_date"], name="uniq_rate_code_date"),
            # курс строго положителен — на него делят при конвертации
            models.CheckConstraint(check=models.Q(rate_uah__gt=0), name="rate_positive"),
        ]
        indexes = [
            # поиск «курс на дату или ближайший ранее» (carry-forward на выходные)
            models.Index(fields=["code", "-rate_date"], name="idx_rate_code_date_desc"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.rate_date}: {self.rate_uah}"
