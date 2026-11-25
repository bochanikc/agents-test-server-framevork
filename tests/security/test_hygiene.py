"""SEC05 — гигиена собственных отчётов: синтетический секрет отсутствует.

Самопроверка генерации: чувствительные заголовки не сохраняются, а синтетический
секрет не попадает в манифест, карточки и прочие артефакты роли. Полностью
автономно, без сети.
"""

from __future__ import annotations

import json

import httpx
import pytest

from fileqa import client as client_mod
from fileqa.client import KEEP_HEADERS
from fileqa.evidence import write_json
from fileqa.manifest import add_object, create, dump

SECRET = "SYNTHETIC-SECRET-fa1c3e7b9d"


@pytest.mark.security
def test_synthetic_secret_absent_from_artifacts(security_root, recorder):
    # 1) whitelist заголовков не сохраняет чувствительные имена.
    for sensitive in ("authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"):
        assert sensitive not in KEEP_HEADERS, f"чувствительный заголовок {sensitive} в whitelist"

    # 2) сериализатор клиента отбрасывает секрет, даже если он в ответе.
    headers = httpx.Headers(
        {"Authorization": f"Bearer {SECRET}", "Content-Type": "application/octet-stream"}
    )
    cleaned = client_mod._clean_headers(headers)
    assert "authorization" not in cleaned
    assert SECRET not in json.dumps(cleaned)

    # 3) наши генераторы (манифест и карточка) пишутся без секрета.
    manifest = create("sec-hygiene", "security.example", "http://example.invalid")
    add_object(manifest, "a.bin", "a.bin", "/files/a.bin", 3, "a" * 64)
    dump(manifest, security_root / "_hygiene_manifest.json")
    write_json(security_root / "_hygiene_case.json", {"case": "SEC05", "note": "no secrets"})

    # 4) скан всех артефактов роли на наличие синтетического секрета.
    found = [
        str(p)
        for p in security_root.rglob("*")
        if p.is_file() and SECRET.encode() in p.read_bytes()
    ]

    recorder("SEC05", status="pass", secret=SECRET, secret_absent=not found, found=found)
    assert not found, f"синтетический секрет обнаружен в артефактах: {found}"
