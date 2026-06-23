"""Django-проект price-tracker.

Импортируем Celery-приложение при старте Django, чтобы shared_task'и
автоматически использовали наш брокер.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
