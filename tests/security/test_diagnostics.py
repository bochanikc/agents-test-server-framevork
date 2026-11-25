"""SEC04 — диагностические ответы: 404/400 не раскрывают внутренние детали.

Проверяем обычные тела ошибок (отсутствующий объект, форма без файловой части).
Тело не должно содержать стектрейсы, абсолютные пути и имена внутренних модулей.
В доказательства сохраняется только минимальный обезличенный фрагмент.
"""

from __future__ import annotations

import json

import httpx
import pytest

from fileqa.fixtures import unique_name

# Признаки утечки внутренностей в теле ошибки.
_LEAK_PATTERNS = (
    "traceback",
    'file "',
    ".py",
    "/app/",
    "/usr/",
    "/var/",
    "/etc/",
    "/root/",
    "node_modules",
    " at com.",
    "sqlalchemy",
    "django",
    "stack trace",
    "exception:",
    "caused by:",
)


def _leaks(body: bytes) -> list:
    text = body.decode("utf-8", errors="ignore").lower()
    return [p for p in _LEAK_PATTERNS if p in text]


def _error_fragment(body: bytes) -> str | None:
    """Короткий обезличенный фрагмент: только строка ошибки, не тело целиком."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    if isinstance(data, dict):
        value = data.get("error") or data.get("detail") or data.get("message")
        if isinstance(value, str):
            return value[:120]
    return None


@pytest.mark.security
def test_error_bodies_minimal(live, origin, recorder, run_id):
    missing = unique_name(run_id=run_id, prefix="qa-sec-missing", suffix=".bin")
    observations: dict = {}

    with httpx.Client(base_url=origin, timeout=10.0, follow_redirects=False) as hc:
        probes = (
            ("404-missing", hc.get("/files/" + missing)),
            ("400-no-file-part", hc.post("/files", files={"name": (None, "qa-sec-probe")})),
        )
        for label, resp in probes:
            body = resp.content
            leaked = _leaks(body)
            observations[label] = {
                "status": resp.status_code,
                "content_type": resp.headers.get("content-type"),
                "leaked": leaked,
                "error_fragment": _error_fragment(body) if not leaked else "<redacted>",
            }

    recorder("SEC04", status="observation", observations=observations)

    for label, obs in observations.items():
        assert not obs["leaked"], (
            f"{label}: тело ошибки раскрывает внутренние детали: {obs['leaked']}"
        )
