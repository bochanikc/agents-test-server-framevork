"""Фикстуры для сценариев 02-e2e.

Один Client на тест (function-scoped), закрывается в teardown. Профиль по
умолчанию — `profiles/live.json`. Адрес цели переопределяется переменными
окружения `FILEQA_PROFILE` (путь к профилю) или `FILEQA_ORIGIN` (адрес цели).

Доказательства пишутся в `artifacts/<run_id>/e2e/` через `write_json`. Базу
артефактов задаёт `FILEQA_ARTIFACTS` (по умолчанию `FRAMEWORK/artifacts/<run_id>`).
`run_id` берётся из `FILEQA_RUN_ID` либо генерируется (метка времени UTC + uuid).

Карточка результата пишется в teardown независимо от исхода теста — чтобы
доказательства сохранялись и при ошибке.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from _pytest.outcomes import Skipped

from fileqa.client import Client, validate_origin
from fileqa.config import (
    environment_type_of,
    field_of,
    limits_of,
    load_profile,
    origin_of,
    required_cases_of,
    upload_path_of,
)
from fileqa.evidence import write_json
from fileqa.manifest import add_object, create, dump
from fileqa.result import new_case

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = FRAMEWORK_ROOT / "profiles" / "live.json"

SOURCE = "02-e2e"


def _new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def _resolve_profile_path() -> Path:
    env = os.environ.get("FILEQA_PROFILE")
    return Path(env).expanduser() if env else DEFAULT_PROFILE


@pytest.fixture(scope="session")
def run_id() -> str:
    return os.environ.get("FILEQA_RUN_ID") or _new_run_id()


@pytest.fixture(scope="session")
def profile() -> dict:
    return load_profile(_resolve_profile_path())


@pytest.fixture(scope="session")
def origin(profile: dict) -> str:
    env = os.environ.get("FILEQA_ORIGIN")
    return validate_origin(env) if env else origin_of(profile)


@pytest.fixture
def client(origin: str, profile: dict) -> Client:
    c = Client(
        origin,
        timeout=float(os.environ.get("FILEQA_TIMEOUT", "15")),
        connect_timeout=float(os.environ.get("FILEQA_CONNECT_TIMEOUT", "8")),
        field=field_of(profile),
        upload_path=upload_path_of(profile),
    )
    yield c
    c.close()


@pytest.fixture(scope="session")
def artifacts_root(run_id: str) -> Path:
    env = os.environ.get("FILEQA_ARTIFACTS")
    root = Path(env).expanduser() if env else FRAMEWORK_ROOT / "artifacts" / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def e2e_dir(artifacts_root: Path) -> Path:
    d = artifacts_root / "e2e"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def manifest(profile: dict, origin: str, run_id: str, artifacts_root: Path) -> dict:
    m = create(
        run_id=run_id,
        profile=profile.get("name", "unknown"),
        origin=origin,
        build=os.environ.get("FILEQA_BUILD", "unknown"),
        quota=limits_of(profile),
        slo=profile.get("slo") or {},
    )
    m["environment_type"] = environment_type_of(profile)
    # Обязательные кейсы фиксируются в манифесте: tools/collect.py без
    # --profile берёт их отсюда, а не из жёсткого списка.
    m["required_cases"] = required_cases_of(profile)
    yield m
    dump(m, artifacts_root / "manifest.json")


@pytest.fixture
def record_upload(manifest: dict, run_id: str):
    """Добавляет принятую загрузку в манифест — остаточные записи запуска."""

    def _add(up: dict):
        # Пакетная загрузка: в манифест попадает каждая принятая часть.
        items = up.get("items")
        if isinstance(items, list) and items:
            added = []
            for item in items:
                receipt = item.get("receipt") or {}
                url = receipt.get("url")
                if not url:
                    continue
                added.append(
                    add_object(
                        manifest,
                        name_sent=item["name_sent"],
                        name_saved=receipt.get("name") or item["name_sent"],
                        url=url,
                        size=item["source_bytes"],
                        sha256=item["source_sha256"],
                        run=run_id,
                    )
                )
            return added or None
        if not up.get("url"):
            return None
        return add_object(
            manifest,
            name_sent=up["name_sent"],
            name_saved=up.get("name") or up["name_sent"],
            url=up["url"],
            size=up["source_bytes"],
            sha256=up["source_sha256"],
            run=run_id,
        )

    return _add


def pytest_runtest_makereport(item, call):
    if call.when != "call":
        return
    if call.excinfo is None:
        outcome = "passed"
    elif isinstance(call.excinfo.value, Skipped):
        outcome = "skipped"
    else:
        outcome = "failed"
    setattr(item, "_e2e_outcome", outcome)


@pytest.fixture(autouse=True)
def record(request, client: Client, e2e_dir: Path, run_id: str, profile: dict) -> dict:
    """Карточка результата сценария. Пишется в teardown независимо от исхода."""
    rec: dict = {}

    def finalize():
        case_id = rec.get("case_id")
        if not case_id:
            return
        card = new_case(SOURCE, run_id, case_id)
        for key, value in rec.items():
            if key != "case_id":
                card[key] = value
        card["trace"] = list(client.trace)
        card["outcome"] = getattr(request.node, "_e2e_outcome", "unknown")
        card["environment_type"] = environment_type_of(profile)
        write_json(e2e_dir / f"{case_id}.json", card)

    request.addfinalizer(finalize)
    return rec
