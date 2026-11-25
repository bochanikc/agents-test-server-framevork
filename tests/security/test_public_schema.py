"""SEC03 — публичная схема: отсутствие лишних внутренних полей.

Проверяемое наблюдение «внутренний путь в публичной схеме»: квитанция загрузки
и/или список могут раскрывать внутренний путь вида /var/example-store/… в поле `path`.
Если политика публичности исключает внутренние пути — раскрытие есть
несоответствие; при неизвестной политике фиксируем наблюдение, вопрос открыт.
"""

from __future__ import annotations

import re

import pytest

from fileqa.fixtures import binary_payload, unique_name

_INTERNAL_PATH_HINTS = ("/app/", "/usr/", "/var/", "/etc/", "/home/", "/root/")

_UUID_RE = re.compile(r"[0-9a-f]{32}")


def _redact(value: str | None) -> str | None:
    """Обезличивает внутренний путь: uuid -> <uuid>, остальное остаётся."""
    if not isinstance(value, str):
        return value
    return _UUID_RE.sub("<uuid>", value)


def _is_internal(path: str | None) -> bool:
    if not isinstance(path, str):
        return False
    return any(h in path for h in _INTERNAL_PATH_HINTS)


@pytest.mark.security
def test_public_schema_no_internal_path(live, client, profile, recorder, run_id):
    name = unique_name(run_id=run_id, prefix="qa-sec", suffix=".bin")
    up = client.upload(name, binary_payload(64))

    receipt_has_path = isinstance(up.get("path"), str)
    receipt_path_internal = _is_internal(up.get("path"))

    lst = client.list_files()
    rows = lst.get("rows") or []
    own_paths = [r.get("path") for r in rows if r.get("name") == up.get("name")]
    list_internal = any(_is_internal(p) for p in own_paths)

    sec = profile.get("security") or {}
    disclosure_policy = sec.get("disclosure_policy", "unknown")

    observed_internal_path = receipt_path_internal or list_internal

    recorder(
        "SEC03",
        status="observation",
        disclosure_policy=disclosure_policy,
        receipt_path_present=receipt_has_path,
        receipt_path_redacted=_redact(up.get("path")),
        list_paths_redacted=[_redact(p) for p in own_paths],
        observed_internal_path=observed_internal_path,
    )

    # Политика исключает внутренний путь — тогда раскрытие есть несоответствие.
    if disclosure_policy == "no-internal-path":
        assert not observed_internal_path, (
            "политика исключает внутренний путь, но публичная выдача раскрывает "
            f"receipt.path={_redact(up.get('path'))!r} / list.paths="
            f"{[_redact(p) for p in own_paths]!r}"
        )
