"""Запись доказательств в каталог запуска.

Каждое свидетельство — файл в `artifacts/<run-id>/<job>/`. Сохраняются
временные метки UTC, метод, путь, статусы, релевантные заголовки и
длина/хеш. Внутренние поля и секреты не сохраняются.
"""

from __future__ import annotations

import json
from pathlib import Path

from .result import utc_now


def write_json(path: str | Path, data) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def write_bytes(path: str | Path, data: bytes) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
