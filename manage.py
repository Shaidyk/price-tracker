#!/usr/bin/env python
"""Точка входа управления Django."""

from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Не найден Django. Активирована ли виртуальная среда?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
