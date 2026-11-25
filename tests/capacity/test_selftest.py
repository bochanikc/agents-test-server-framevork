"""Самопроверка оракулов квот и обработки неподготовленного стенда (без сети).

Показывает, что оракул корректно считает границу квоты, а live-профиль
(capabilities=[]) опознаётся как «нужен управляемый стенд». Дублёр и оракул —
две независимые реализации; их согласие подтверждает арифметику C01–C03.
"""

from urllib.parse import quote

import httpx
import pytest

from fileqa.client import Client
from fileqa.config import load_profile
from fileqa.digest import sha256
from fileqa.fixtures import binary_payload


def _step(client, model, name, data):
    up = client.upload(name, data)
    pred = model.apply(name, len(data))
    assert pred["accept"] == (up["status"] < 400), (name, pred, up["status"])
    return up, pred


@pytest.mark.capacity
def test_oracle_object_count_boundary(quota_double, quota_model_cls):
    N = 8
    quota_double.configure(object_count=N, logical_bytes=None)
    model = quota_model_cls(object_count=N, logical_bytes=None)
    with Client(quota_double.origin) as c:
        for i in range(N - 1):
            _step(c, model, f"c01-{i}.bin", binary_payload(4, seed=i))
        up, pred = _step(c, model, "c01-8.bin", binary_payload(4, seed=N))
        assert pred["accept"] and up["status"] == 201
        up, pred = _step(c, model, "c01-9.bin", binary_payload(4, seed=N + 1))
        assert not pred["accept"] and pred["reason"] == "object_count"
        assert model.count == N
        assert quota_double.store.count == N


@pytest.mark.capacity
def test_oracle_logical_bytes_boundary(quota_double, quota_model_cls):
    B = 32768
    quota_double.configure(logical_bytes=B, object_count=None)
    model = quota_model_cls(logical_bytes=B, object_count=None)
    with Client(quota_double.origin) as c:
        for size, seed in ((16384, 1), (16383, 2), (1, 3)):
            up, pred = _step(c, model, f"c02-{seed}.bin", binary_payload(size, seed=seed))
            assert pred["accept"] and up["status"] == 201
        assert model.bytes == B
        up, pred = _step(c, model, "c02-over.bin", binary_payload(1, seed=9))
        assert not pred["accept"] and pred["reason"] == "logical_bytes"
        assert quota_double.store.bytes == B
        dl = c.download("/files/c02-1.bin")
        assert dl["status"] == 200 and dl["sha256"] == sha256(binary_payload(16384, seed=1))


@pytest.mark.capacity
def test_oracle_replace_delta(quota_double, quota_model_cls):
    B = 32768
    quota_double.configure(logical_bytes=B, object_count=None, collision="replace")
    model = quota_model_cls(logical_bytes=B, object_count=None, collision="replace")
    with Client(quota_double.origin) as c:
        name = "c03-replace.bin"
        _step(c, model, name, binary_payload(16384, seed=1))
        up, pred = _step(c, model, name, binary_payload(32767, seed=2))
        assert pred["accept"] and up["status"] == 201  # дельта, не наивная сумма
        assert model.bytes == 32767 and model.count == 1
        _step(c, model, name, binary_payload(32768, seed=3))
        up, pred = _step(c, model, name, binary_payload(32769, seed=4))
        assert not pred["accept"] and pred["reason"] == "logical_bytes"
        dl = c.download("/files/" + quote(name))
        assert dl["status"] == 200 and dl["bytes"] == 32768
        assert quota_double.store.bytes == 32768


@pytest.mark.capacity
def test_oracle_delete_frees(quota_double, quota_model_cls):
    B = 32768
    quota_double.configure(logical_bytes=B, object_count=None, collision="replace")
    model = quota_model_cls(logical_bytes=B, object_count=None, collision="replace")
    with Client(quota_double.origin) as c:
        a, b, cc = "c03-a.bin", "c03-b.bin", "c03-c.bin"
        _step(c, model, a, binary_payload(30000, seed=1))
        _step(c, model, b, binary_payload(2000, seed=2))
        up, pred = _step(c, model, cc, binary_payload(1000, seed=3))
        assert not pred["accept"] and up["status"] >= 400  # 33000 > B

        r = httpx.delete(quota_double.origin + "/files/" + quote(b))
        assert r.status_code == 200
        model.delete(b)
        assert model.bytes == 30000

        up, pred = _step(c, model, cc, binary_payload(1000, seed=3))
        assert pred["accept"] and up["status"] == 201
        assert model.bytes == 31000


@pytest.mark.capacity
def test_oracle_versioned_arithmetic(quota_model_cls):
    model = quota_model_cls(logical_bytes=1000, object_count=10, collision="versioned")
    d = model.apply("a.bin", 400)
    assert d["accept"] and model.count == 1 and model.bytes == 400
    d = model.apply("a.bin", 400)  # новая версия: +1 объект, +400 байт
    assert d["accept"] and model.count == 2 and model.bytes == 800
    d = model.apply("a.bin", 300)  # 1100 > 1000 → отказ по сумме
    assert not d["accept"] and d["reason"] == "logical_bytes"


@pytest.mark.capacity
def test_live_profile_not_managed(framework_root, is_managed):
    p = load_profile(framework_root / "profiles" / "live.json")
    ok, reason = is_managed(p)
    assert not ok
    assert "нужен управляемый стенд" in reason


@pytest.mark.capacity
def test_disposable_profile_managed(framework_root, is_managed):
    p = load_profile(framework_root / "profiles" / "disposable.example.json")
    ok, reason = is_managed(p)
    assert ok, reason


@pytest.mark.capacity
def test_reconcile_complete(reconcile_fn, quota_double):
    quota_double.configure()
    objs = []
    with Client(quota_double.origin) as c:
        for i in range(4):
            name = f"snap-{i}.bin"
            data = binary_payload(1024, seed=i)
            c.upload(name, data)
            objs.append({"name_saved": name, "bytes": len(data), "sha256": sha256(data)})
        rows = c.list_files()["rows"]
        assert reconcile_fn(rows, objs)["complete"] is True
        res = reconcile_fn(rows, objs + [{"name_saved": "ghost.bin", "bytes": 1, "sha256": "a" * 64}])
        assert res["missing"] == ["ghost.bin"] and res["complete"] is False
