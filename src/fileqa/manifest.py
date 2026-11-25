"""Манифест запуска: общий контракт между Python-тестами и k6.

Манифест — JSON с версией схемы. Он одинаково понимается Python и JavaScript:
размер объекта — целое число байтов, SHA-256 — 64 символа hex нижнего
регистра. Секреты в манифест не попадают.

Структура:
  schema, version, run_id, utc, build, profile, origin, quota, slo, tools,
  objects: [{name_sent, name_saved, url, bytes, sha256, run}]
"""

from __future__ import annotations

import json
from pathlib import Path

from .digest import is_hex_sha256

SCHEMA = "fileqa-manifest"
VERSION = 1


def create(
    run_id: str,
    profile: str,
    origin: str,
    build: str = "unknown",
    quota: dict | None = None,
    slo: dict | None = None,
    tools: dict | None = None,
) -> dict:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "run_id": run_id,
        "utc": _utc_now(),
        "build": build,
        "profile": profile,
        "origin": origin,
        "quota": quota or {},
        "slo": slo or {},
        "tools": tools if tools is not None else tool_versions(),
        "objects": [],
    }


def tool_versions() -> dict:
    """Версии инструментов, известные в момент создания манифеста.

    k6 заполняет свою версию отдельно в сводке прогона (k6 не запускается
    внутри Python), поэтому здесь его нет.
    """
    import platform

    from . import __version__

    return {
        "python": platform.python_version(),
        "fileqa": __version__,
    }


def add_object(
    manifest: dict,
    name_sent: str,
    name_saved: str,
    url: str,
    size: int,
    sha256: str,
    run: str | None = None,
) -> dict:
    """Добавляет объект и возвращает его запись."""
    obj = {
        "name_sent": name_sent,
        "name_saved": name_saved,
        "url": url,
        "bytes": int(size),
        "sha256": sha256,
        "run": run or manifest["run_id"],
    }
    manifest["objects"].append(obj)
    return obj


def validate(manifest: dict) -> None:
    """Проверяет структуру и типы. Бросает ValueError при расхождении."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"неизвестная схема манифеста {manifest.get('schema')!r}")
    if manifest.get("version") != VERSION:
        raise ValueError(f"неизвестная версия манифеста {manifest.get('version')!r}")
    for key in ("run_id", "profile", "origin", "build"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"манифест без поля {key}")
    if not isinstance(manifest.get("objects"), list):
        raise ValueError("objects должен быть массивом")
    for obj in manifest["objects"]:
        if not isinstance(obj.get("bytes"), int) or obj["bytes"] < 0:
            raise ValueError("bytes объекта должен быть неотрицательным целым")
        if not is_hex_sha256(obj.get("sha256", "")):
            raise ValueError(f"sha256 объекта неверен: {obj.get('sha256')!r}")
        if not isinstance(obj.get("url"), str) or not obj["url"]:
            raise ValueError("объект без url")


def dump(manifest: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return data


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
