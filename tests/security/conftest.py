"""Фикстуры роли 05-security: профиль, точка входа, клиент, каталог доказательств.

Запуск (режим «подготовлено, прогон отложен» — только сбор):
    cd framework
    python3 -m pytest tests/security --collect-only -q

При фактическом прогоне цель задаётся переменными окружения:
    FILEQA_PROFILE=<путь к профилю>   # по умолчанию profiles/security.example.json
    FILEQA_ORIGIN=<http(s)://host>     # переопределяет origin из профиля
    FILEQA_RUN_ID=<run-id>             # по умолчанию генерируется

Сетевые проверки работают только на СОБСТВЕННЫХ данных (уникальные имена,
собственная фикстура) и не выполняют пентест. Если точка входа недоступна,
проверка фиксируется как incomplete и пропускается (skip), а не падает: это
отличает «стенд недоступен» от «свойство нарушено». Секреты в артефакты не
записываются (см. SEC05).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fileqa.client import Client
from fileqa.config import (
    field_of,
    load_profile,
    origin_of,
    upload_path_of,
)
from fileqa.evidence import write_json
from fileqa.result import new_case

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _default_profile() -> Path:
    return FRAMEWORK_ROOT / "profiles" / "security.example.json"


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _write(security_root: Path, run_id: str, case_id: str, **fields) -> dict:
    """Записывает карточку результата в каталог доказательств и возвращает её."""
    card = new_case("05-security", run_id, case_id, **fields)
    write_json(security_root / f"{case_id}.json", card)
    return card


@pytest.fixture(scope="session")
def framework_root() -> Path:
    return FRAMEWORK_ROOT


@pytest.fixture(scope="session")
def profile() -> dict:
    raw = _env("FILEQA_PROFILE")
    path = Path(raw) if raw else _default_profile()
    return load_profile(path)


@pytest.fixture(scope="session")
def origin(profile: dict) -> str:
    override = _env("FILEQA_ORIGIN")
    return override if override else origin_of(profile)


@pytest.fixture(scope="session")
def run_id() -> str:
    return _env("FILEQA_RUN_ID") or _default_run_id()


@pytest.fixture(scope="session")
def security_root(run_id: str) -> Path:
    p = FRAMEWORK_ROOT / "artifacts" / run_id / "security"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture(scope="session")
def recorder(security_root: Path, run_id: str):
    """Возвращает функцию записи карточки результата роли."""

    def _record(case_id: str, **fields) -> dict:
        return _write(security_root, run_id, case_id, **fields)

    return _record


@pytest.fixture(scope="session")
def client(origin: str, profile: dict) -> Client:
    c = Client(
        origin,
        field=field_of(profile),
        upload_path=upload_path_of(profile),
        timeout=15.0,
        connect_timeout=5.0,
    )
    yield c
    c.close()


@pytest.fixture(scope="session")
def live(client: Client, origin: str, security_root: Path, run_id: str) -> dict:
    """Однократно проверяет доступность точки входа на сессию.

    Сетевые проверки полагаются на этот фикстур: если стенд недоступен, они
    пропускаются (skip) с записанной карточкой incomplete — это не провал
    защитного свойства, а отсутствие стенда.
    """
    try:
        r = client.health()
    except Exception as exc:  # httpx.ConnectError/ConnectTimeout и прочие сетевые
        _write(
            security_root,
            run_id,
            "SEC-REACH",
            status="incomplete",
            reason=f"точка входа {origin} недоступна: {type(exc).__name__}",
        )
        pytest.skip(
            f"точка входа {origin} недоступна ({type(exc).__name__}); прогон отложен"
        )
    _write(
        security_root,
        run_id,
        "SEC-REACH",
        status="ok",
        origin=origin,
        health_status=r.get("status"),
    )
    return r
