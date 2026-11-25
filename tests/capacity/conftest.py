"""Fixtures, оракул квот и синтетический дублёр для сценариев ёмкости (C01–C05).

Три разных вопроса хранения не смешиваются:
  * квота количества объектов      -> limits.object_count;
  * квота логического содержимого  -> limits.logical_bytes;
  * эксплуатационный объём (метаданные/версии/реплики/бэкапы) -> C05, отдельно.

На живом профиле (capabilities пусты) C01–C03 получают skip «нужен управляемый
стенд» (не xfail, не pass). Самопроверка арифметики — на синтетическом дублёре
с квотами, без сети.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy as email_policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote, unquote

import pytest

from fileqa.client import Client
from fileqa.config import (
    capabilities_of,
    field_of,
    limits_of,
    load_profile,
    origin_of,
    policy_of,
    upload_path_of,
)
from fileqa.evidence import write_json
from fileqa.fixtures import run_marker
from fileqa.result import new_case

ROLE = "03-capacity"
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


def is_rejected(status: int | None) -> bool:
    """Отказ — любой ответ 4xx/5xx. 2xx/3xx не считается отказом."""
    return status is not None and status >= 400


def is_quota_managed(profile: dict) -> tuple[bool, str]:
    """True, если профиль даёт управляемый стенд с квотами для C01–C03."""
    caps = capabilities_of(profile)
    limits = limits_of(profile)
    missing = {"reset", "quotas", "namespace"} - caps
    if missing:
        return False, (
            "нужен управляемый стенд: нет capability "
            + ", ".join(sorted(missing))
            + " (capabilities=" + (", ".join(sorted(caps)) if caps else "[]") + ")"
        )
    if limits["object_count"] is None and limits["logical_bytes"] is None:
        return False, "нужен управляемый стенд: limits.object_count и limits.logical_bytes не заданы"
    return True, ""


def _resolve_profile() -> dict:
    path = os.environ.get("FILEQA_PROFILE")
    if path:
        return load_profile(path)
    origin = os.environ.get("FILEQA_ORIGIN")
    if origin:
        return {
            "schema": "fileqa-profile",
            "version": 1,
            "name": "env-origin",
            "description": "Профиль, собранный из FILEQA_ORIGIN; квоты не подтверждены.",
            "origin": origin,
            "limits": {
                "single_file_bytes": None,
                "object_count": None,
                "logical_bytes": None,
                "scope": "unknown",
            },
            "policy": {"collision": "unknown", "names": "unknown", "delete": False},
            "upload": {"field": "file", "path": "/files"},
            "capabilities": [],
            "_path": "<env:FILEQA_ORIGIN>",
        }
    return load_profile(FRAMEWORK_ROOT / "profiles" / "live.json")


@dataclass
class Stand:
    profile: dict
    origin: str
    limits: dict
    capabilities: set
    policy: dict
    client: Client
    run_id: str
    marker: str
    artifacts: Path


# --------------------------------------------------------------------------- #
# Оракул квот: прогноз принятия операции и накопленное состояние.             #
# Отдельная реализация от дублёра — самопроверка сверяет их между собой.      #
# --------------------------------------------------------------------------- #

class QuotaModel:
    """Чистая арифметика квот.

    Различает:
      * replace  — то же имя заменяет объект: число не растёт, сумма меняется;
      * versioned — то же имя даёт новую версию: +1 объект, +size байт;
      * новое имя  — +1 объект, +size байт.
    Пустой объект (size=0) занимает слот количества, но не добавляет байтов.
    """

    def __init__(self, object_count=None, logical_bytes=None, collision="replace"):
        self.object_count = object_count
        self.logical_bytes = logical_bytes
        self.collision = collision
        self.units: list[tuple[str, int]] = []  # (name, size)

    @property
    def count(self):
        return len(self.units)

    @property
    def bytes(self):
        return sum(s for _, s in self.units)

    def predict(self, name: str, size: int) -> dict:
        exists = any(n == name for n, _ in self.units)
        if self.collision == "reject" and exists:
            return {"accept": False, "reason": "collision"}
        if self.collision == "replace" and exists:
            new_units = [(n, s) for n, s in self.units if n != name] + [(name, size)]
        else:
            new_units = self.units + [(name, size)]
        new_count = len(new_units)
        new_bytes = sum(s for _, s in new_units)
        if self.object_count is not None and new_count > self.object_count:
            return {"accept": False, "reason": "object_count",
                    "projected_count": new_count, "projected_bytes": new_bytes}
        if self.logical_bytes is not None and new_bytes > self.logical_bytes:
            return {"accept": False, "reason": "logical_bytes",
                    "projected_count": new_count, "projected_bytes": new_bytes}
        return {"accept": True, "reason": "ok",
                "projected_count": new_count, "projected_bytes": new_bytes}

    def apply(self, name: str, size: int) -> dict:
        d = self.predict(name, size)
        if not d["accept"]:
            return d
        if self.collision == "replace":
            self.units = [(n, s) for n, s in self.units if n != name] + [(name, size)]
        else:
            self.units.append((name, size))
        return d

    def delete(self, name: str) -> None:
        self.units = [(n, s) for n, s in self.units if n != name]


# --------------------------------------------------------------------------- #
# Синтетический дублёр с квотами. Независимая от QuotaModel реализация.        #
# --------------------------------------------------------------------------- #

class QuotaStore:
    """Состояние и учёт квот дублёра (replace/reject; delete — отдельным путём)."""

    def __init__(self, object_count=None, logical_bytes=None, collision="replace", single_file_bytes=None):
        self.object_count = object_count
        self.logical_bytes = logical_bytes
        self.collision = collision
        self.single_file_bytes = single_file_bytes
        self.files: dict = {}
        self.rejected: list = []

    @property
    def count(self):
        return len(self.files)

    @property
    def bytes(self):
        return sum(len(e["data"]) for e in self.files.values())

    def decide(self, name: str, data: bytes) -> dict:
        size = len(data)
        if self.single_file_bytes is not None and size > self.single_file_bytes:
            self.rejected.append({"name": name, "size": size, "reason": "single_file_bytes"})
            return {"accept": False, "reason": "single_file_bytes"}
        exists = name in self.files
        if self.collision == "reject" and exists:
            self.rejected.append({"name": name, "size": size, "reason": "collision"})
            return {"accept": False, "reason": "collision"}
        new_count = self.count if (exists and self.collision == "replace") else self.count + 1
        old = len(self.files[name]["data"]) if (exists and self.collision == "replace") else 0
        new_bytes = self.bytes - old + size
        if self.object_count is not None and new_count > self.object_count:
            self.rejected.append({"name": name, "size": size, "reason": "object_count"})
            return {"accept": False, "reason": "object_count"}
        if self.logical_bytes is not None and new_bytes > self.logical_bytes:
            self.rejected.append({"name": name, "size": size, "reason": "logical_bytes"})
            return {"accept": False, "reason": "logical_bytes"}
        return {"accept": True, "reason": "ok",
                "projected_count": new_count, "projected_bytes": new_bytes}


class _QuotaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status, data, mime="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    @property
    def store(self):
        return self.server.store

    def _storage_path(self, name):
        return f"/var/example-store/{uuid.uuid4().hex}_{name}"

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, b'{"status":"ok"}')
        if self.path == "/files":
            rows = [
                {"name": n, "path": e["path"], "size": len(e["data"]),
                 "content_type": e["content_type"], "fields": []}
                for n, e in self.store.files.items()
            ]
            return self._send(200, json.dumps(rows).encode())
        name = unquote(self.path.removeprefix("/files/"))
        if name in self.store.files:
            e = self.store.files[name]
            return self._send(200, e["data"], e["content_type"],
                              extra={"Content-Disposition": f'attachment; filename="{name}"'})
        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path != "/files":
            return self._send(404, b"{}")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        header = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
        parts = BytesParser(policy=email_policy.default).parsebytes(header + body).iter_parts()
        for part in parts:
            if part.get_param("name", header="Content-Disposition") != "file":
                continue
            name = part.get_filename()
            data = part.get_payload(decode=True) or b""
            content_type = part.get("Content-Type", "application/octet-stream")
            decision = self.store.decide(name, data)
            if not decision["accept"]:
                return self._send(413, json.dumps({"error": "quota exceeded",
                                                   "reason": decision["reason"]}).encode())
            path = self.store.files[name]["path"] if name in self.store.files else self._storage_path(name)
            self.store.files[name] = {"data": data, "content_type": content_type, "path": path}
            saved = {"name": name, "path": path, "size": len(data), "content_type": content_type,
                     "fields": [], "url": "/files/" + quote(name)}
            return self._send(201, json.dumps({"uploaded": [saved]}).encode())
        return self._send(400, b'{"error":"file required"}')

    def do_DELETE(self):
        name = unquote(self.path.removeprefix("/files/"))
        if name in self.store.files:
            del self.store.files[name]
            return self._send(200, b'{"deleted": true}')
        return self._send(404, b'{"error":"not found"}')


class _QuotaServer:
    def __init__(self):
        self._store = QuotaStore()
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _QuotaHandler)
        self._http.store = self._store
        self.port = self._http.server_port
        self._thread = Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()

    @property
    def store(self):
        return self._store

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def configure(self, **kw):
        self._store = QuotaStore(**kw)
        self._http.store = self._store

    def reset(self):
        self._store.files.clear()
        self._store.rejected.clear()

    def close(self):
        self._http.shutdown()
        self._http.server_close()
        self._thread.join()


# --------------------------------------------------------------------------- #
# Прикладные помощники сценариев.                                              #
# --------------------------------------------------------------------------- #

def _reconcile(rows: list, manifest_objects: list) -> dict:
    """Сверка листинга с собственным манифестом: пропуски, дубли, расхождение size."""
    by_name: dict = {}
    dupes: list = []
    for r in rows:
        n = r.get("name")
        if n in by_name:
            dupes.append(n)
        by_name[n] = r
    missing: list = []
    size_mismatch: list = []
    for o in manifest_objects:
        n = o.get("name_saved") or o.get("name")
        if n not in by_name:
            missing.append(n)
        elif by_name[n].get("size") != o.get("bytes"):
            size_mismatch.append({"name": n, "listed": by_name[n].get("size"),
                                  "expected": o.get("bytes")})
    return {
        "listed": len(rows),
        "expected": len(manifest_objects),
        "missing": missing,
        "dupes": dupes,
        "size_mismatch": size_mismatch,
        "complete": not missing and not dupes and not size_mismatch,
    }


class _Helpers:
    def __init__(self, stand: Stand, framework_root: Path):
        self.stand = stand
        self.out = framework_root / "artifacts" / stand.run_id / "capacity"
        self.is_rejected = is_rejected
        self.reconcile = _reconcile

    def record(self, case_id: str, **fields) -> dict:
        card = new_case(ROLE, self.stand.run_id, case_id, **fields)
        write_json(self.out / f"{case_id}.json", card)
        return card

    def skip(self, case_id: str, reason: str):
        self.record(case_id, status="skip", reason=reason)
        pytest.skip(f"{case_id}: {reason}")

    def require_quota(self, case_id: str, count: bool = False,
                      bytes_: bool = False, delete: bool = False):
        ok, reason = is_quota_managed(self.stand.profile)
        if not ok:
            self.skip(case_id, reason)
        if count and self.stand.limits["object_count"] is None:
            self.skip(case_id, "limits.object_count не задан — квота количества неизвестна")
        if bytes_ and self.stand.limits["logical_bytes"] is None:
            self.skip(case_id, "limits.logical_bytes не задан — квота суммы неизвестна")
        if delete and not self.stand.policy["delete"]:
            self.skip(case_id, "удаление не подтверждено (policy.delete=false)")

    def list_rows(self):
        r = self.stand.client.list_files()
        rows = r.get("rows")
        return r, (rows if isinstance(rows, list) else [])

    def baseline(self) -> dict:
        r, rows = self.list_rows()
        return {
            "status": r["status"],
            "count": len(rows),
            "bytes": sum(int(x.get("size") or 0) for x in rows),
            "rows": rows,
        }

    def preamble(self, case_id: str, count: bool = False,
                 bytes_: bool = False, delete: bool = False) -> dict:
        """Гейт по квотам + фиксация исходного использования и ОБОИХ лимитов."""
        self.require_quota(case_id, count=count, bytes_=bytes_, delete=delete)
        base = self.baseline()
        self.record(
            case_id + ".preamble",
            limits=self.stand.limits,
            scope=self.stand.limits.get("scope"),
            capabilities=sorted(self.stand.capabilities),
            policy=self.stand.policy,
            starting_usage={"objects": base["count"], "bytes": base["bytes"]},
        )
        return base

    def fetch_check(self, url: str, expected_sha: str, expected_size: int) -> dict:
        d = self.stand.client.download(url)
        return {
            "status": d["status"],
            "bytes": d["bytes"],
            "sha256": d["sha256"],
            "sha_ok": d["sha256"] == expected_sha,
            "size_ok": d["bytes"] == expected_size,
        }


# --------------------------------------------------------------------------- #
# Fixtures.                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def framework_root():
    return FRAMEWORK_ROOT


@pytest.fixture(scope="session")
def run_id():
    return os.environ.get("FILEQA_RUN_ID") or (uuid.uuid4().hex[:12] + "-capacity")


@pytest.fixture(scope="session")
def profile():
    return _resolve_profile()


@pytest.fixture
def stand(profile, run_id, framework_root):
    c = Client(
        origin_of(profile),
        field=field_of(profile),
        upload_path=upload_path_of(profile),
    )
    st = Stand(
        profile=profile,
        origin=origin_of(profile),
        limits=limits_of(profile),
        capabilities=capabilities_of(profile),
        policy=policy_of(profile),
        client=c,
        run_id=run_id,
        marker=run_marker(run_id),
        artifacts=framework_root / "artifacts" / run_id,
    )
    yield st
    c.close()


@pytest.fixture
def helpers(stand, framework_root):
    return _Helpers(stand, framework_root)


@pytest.fixture
def quota_double():
    server = _QuotaServer()
    yield server
    server.close()


@pytest.fixture
def quota_model_cls():
    return QuotaModel


@pytest.fixture
def is_managed():
    return is_quota_managed


@pytest.fixture
def reconcile_fn():
    return _reconcile
