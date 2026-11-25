"""Загрузка и проверка профилей стенда.

Профиль — JSON с версией схемы. Поля, которые владелец не подтвердил,
остаются `unknown` (строка) или `null` (число). Отсутствующее значение не
выдумывается. Источник каждой настройки помечается в `sources`:
`agreement` (договорённость), `stand` (конфигурация стенда), `observation`
(наблюдение в прогоне) или `assumed` (предложение для фикстур).
"""

from __future__ import annotations

import json
from pathlib import Path

from .client import validate_origin

SCHEMA = "fileqa-profile"
VERSION = 1


def load_profile(path: str | Path) -> dict:
    """Читает профиль и проверяет минимальную структуру. Возвращает dict."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{p}: неизвестная схема профиля {data.get('schema')!r}")
    if data.get("version") != VERSION:
        raise ValueError(f"{p}: неизвестная версия профиля {data.get('version')!r}")
    if "name" not in data:
        raise ValueError(f"{p}: профиль без имени")
    data["_path"] = str(p.resolve())
    return data


def origin_of(profile: dict) -> str:
    origin = profile.get("origin")
    if not origin:
        raise ValueError("профиль не задаёт origin (адрес цели)")
    return validate_origin(origin)


def field_of(profile: dict) -> str:
    return profile.get("upload", {}).get("field", "file")


def upload_path_of(profile: dict) -> str:
    return profile.get("upload", {}).get("path", "/files")


def limits_of(profile: dict) -> dict:
    """Лимиты профиля. Отсутствующие значения — None (неизвестно)."""
    limits = profile.get("limits", {})
    return {
        "single_file_bytes": limits.get("single_file_bytes"),
        "object_count": limits.get("object_count"),
        "logical_bytes": limits.get("logical_bytes"),
        "scope": limits.get("scope", "unknown"),
    }


def policy_of(profile: dict) -> dict:
    policy = profile.get("policy", {})
    return {
        "collision": policy.get("collision", "unknown"),
        "names": policy.get("names", "unknown"),
        "delete": bool(policy.get("delete", False)),
    }


def capabilities_of(profile: dict) -> set:
    return set(profile.get("capabilities", []))


def required_cases_of(profile: dict) -> list[str]:
    """Обязательные кейсы прогона из `required.cases` профиля.

    Пустой список означает «профиль не задаёт обязательные проверки»; это не
    повод считать прогон успешным (см. tools/collect.py).
    """
    required = profile.get("required") or {}
    cases = required.get("cases") if isinstance(required, dict) else None
    if not isinstance(cases, list):
        return []
    return [str(case).strip() for case in cases if str(case).strip()]


def environment_type_of(profile: dict) -> str:
    """Тип среды: synthetic-double / managed-stand / live.

    Явно отличает тестовый дублёр от реального стенда в отчёте
    (architecture.md: «в отчёте указывать тип среды»).
    """
    caps = set(profile.get("capabilities", []))
    if "synthetic-double" in caps:
        return "synthetic-double"
    if caps & {"reset", "quotas", "namespace"}:
        return "managed-stand"
    return "live"
