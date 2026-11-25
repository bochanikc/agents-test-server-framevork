"""Общий формат записи результата, который роли передают координатору.

Каждая карточка несёт `source` (роль/инструмент), `run_id` и `case_id`, чтобы
манифест и отчёт могли связать наблюдение с запуском. Поля обязательны для
любой роли; остальное — произвольные данные конкретного сценария.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Текущее время в UTC по ISO 8601 с часовым поясом."""
    return datetime.now(timezone.utc).isoformat()


def new_case(source: str, run_id: str, case_id: str, **fields) -> dict:
    """Карточка результата с обязательными служебными полями."""
    record = {
        "source": source,
        "run_id": run_id,
        "case_id": case_id,
        "utc": utc_now(),
    }
    record.update(fields)
    return record


def incomplete(source: str, run_id: str, case_id: str, reason: str, **fields) -> dict:
    """Сценарий, который не удалось довести до сравнения (код раннера 2)."""
    record = new_case(source, run_id, case_id, status="incomplete", reason=reason)
    record.update(fields)
    return record
