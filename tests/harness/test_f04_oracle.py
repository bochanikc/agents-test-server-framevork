"""Самопроверка оракула F04 (офлайн, без сети).

REV-13: сам оракул `_f04_oracle` раньше проверялся только живым прогоном.
Здесь он вызывается напрямую на синтетических наблюдениях — та же функция,
без копии логики. Проверяются три различимых исхода:

  * policy=unknown, ссылка B отдаёт байты A → fail «устаревшая редакция»;
  * policy=unknown, ссылка B отдаёт байты B → pass;
  * policy=reject, B принят (2xx) → fail.
"""

import importlib.util

import pytest

SHA_A = "a" * 64
SHA_B = "b" * 64


def _load_oracle(framework_root):
    path = framework_root / "tests" / "e2e" / "test_collision.py"
    spec = importlib.util.spec_from_file_location("fileqa_f04_collision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._f04_oracle


def _up(sha: str, status: int = 201) -> dict:
    return {
        "source_sha256": sha,
        "source_bytes": 64,
        "status": status,
        "url": "/files/qa-dup.bin",
    }


def _read(sha: str, status: int = 200) -> dict:
    return {"status": status, "sha256": sha}


def _matches() -> list:
    return [{"name": "qa-dup.bin", "size": 64}]


def _reads(sha: str, count: int = 3) -> list:
    return [_read(sha) for _ in range(count)]


def test_unknown_b_url_returns_a_is_fail(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "unknown",
        _up(SHA_A),
        _up(SHA_B),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_A),
        _matches(),
    )
    assert verdict == "fail"
    assert "устаревшая редакция" in detail


def test_unknown_b_url_returns_b_is_pass(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "unknown",
        _up(SHA_A),
        _up(SHA_B),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_B),
        _matches(),
    )
    assert verdict == "pass", detail


def test_reject_but_b_accepted_is_fail(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "reject",
        _up(SHA_A),
        _up(SHA_B, status=200),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_B),
        _matches(),
    )
    assert verdict == "fail"
    assert "reject" in detail


@pytest.mark.parametrize("policy", ["replace", "versioned"])
def test_known_policy_b_url_returns_a_is_fail(framework_root, policy):
    # Для replace/versioned ссылка B тоже обязана отдавать B.
    oracle = _load_oracle(framework_root)
    verdict, _ = oracle(
        policy,
        _up(SHA_A),
        _up(SHA_B),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_A),
        _matches(),
    )
    assert verdict == "fail"


# --- Регрессии T10: ложный pass на 5xx, постороннем 4xx, сети и без URL ---


def _up_with(sha: str, status=201, url="/files/qa-dup.bin", **extra) -> dict:
    up = _up(sha, status=status)
    up["url"] = url
    up.update(extra)
    return up


@pytest.mark.parametrize("policy", ["unknown", "reject"])
def test_server_500_is_fail_even_if_a_still_reads(framework_root, policy):
    # Пример из readiness-audit.json: 500 при B не является допустимым отказом.
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        policy,
        _up(SHA_A),
        _up_with(SHA_B, status=500, url=None),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_A),
        _matches(),
    )
    assert verdict == "fail"
    assert "500" in detail


@pytest.mark.parametrize("status", [400, 404, 413, 429])
def test_other_client_error_is_not_expected_rejection(framework_root, status):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "unknown",
        _up(SHA_A),
        _up_with(SHA_B, status=status, url=None),
        _read(SHA_A),
        _reads(SHA_A),
        [],
        _matches(),
    )
    assert verdict == "fail"
    assert "409" in detail


@pytest.mark.parametrize("status", [None, 0])
def test_transport_failure_is_fail(framework_root, status):
    oracle = _load_oracle(framework_root)
    up_b = _up_with(SHA_B, status=status, url=None)
    up_b["error"] = "ConnectError: synthetic"
    verdict, detail = oracle(
        "unknown",
        _up(SHA_A),
        up_b,
        _read(SHA_A),
        _reads(SHA_A),
        [],
        _matches(),
    )
    assert verdict == "fail"
    assert "транспорт" in detail.lower()


def test_accepted_b_without_url_is_fail(framework_root):
    # Ссылка A не подставляется вместо отсутствующей ссылки B.
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "replace",
        _up(SHA_A),
        _up_with(SHA_B, status=201, url=None),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_B),
        _matches(),
    )
    assert verdict == "fail"
    assert "url" in detail


def test_conflict_409_with_unchanged_a_is_pass(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "reject",
        _up(SHA_A),
        _up_with(SHA_B, status=409, url=None),
        _read(SHA_A),
        _reads(SHA_A),
        [],
        _matches(),
    )
    assert verdict == "pass", detail


def test_conflict_409_with_extra_row_is_fail(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "unknown",
        _up(SHA_A),
        _up_with(SHA_B, status=409, url=None),
        _read(SHA_A),
        _reads(SHA_A),
        [],
        [{"name": "qa-dup.bin", "size": 64}, {"name": "qa-dup.bin", "size": 64}],
    )
    assert verdict == "fail"
    assert "строк" in detail


@pytest.mark.parametrize("policy", ["replace", "versioned"])
def test_accepted_b_with_own_url_and_b_bytes_is_pass(framework_root, policy):
    oracle = _load_oracle(framework_root)
    url_b = "/files/qa-dup.bin" if policy == "replace" else "/files/qa-dup-b.bin"
    reads_a = _reads(SHA_B) if policy == "replace" else _reads(SHA_A)
    verdict, detail = oracle(
        policy,
        _up(SHA_A),
        _up_with(SHA_B, status=201, url=url_b),
        _read(SHA_A),
        reads_a,
        _reads(SHA_B),
        _matches(),
    )
    assert verdict == "pass", detail


def test_versioned_same_url_for_both_is_fail(framework_root):
    oracle = _load_oracle(framework_root)
    verdict, detail = oracle(
        "versioned",
        _up(SHA_A),
        _up_with(SHA_B, status=201, url="/files/qa-dup.bin"),
        _read(SHA_A),
        _reads(SHA_A),
        _reads(SHA_B),
        _matches(),
    )
    assert verdict == "fail"
    assert "один url" in detail


# --- Тот же путь через обычный вход теста test_f04_collision ---


class _FakeClient:
    """Локальный двойник для входа F04: без сети, по одному ответу на A и B."""

    def __init__(self, b_status=201, b_url="/files/b", b_error=None, a_after="a"):
        self.b_status = b_status
        self.b_url = b_url
        self.b_error = b_error
        self.a_after = a_after
        self.index = 0
        self.trace: list = []
        self._names: list[str] = []

    def upload(self, name, data, content_type="application/octet-stream"):
        self.index += 1
        is_b = self.index % 2 == 0
        if not is_b:
            self._names.append(name)
            return {
                "status": 201, "name": name, "url": f"/files/a{self.index}",
                "source_bytes": len(data), "source_sha256": SHA_A,
                "receipt": {"uploaded": [{"name": name, "url": f"/files/a{self.index}"}]},
            }
        if self.b_error is not None:
            raise self.b_error
        return {
            "status": self.b_status, "name": name,
            "url": None if self.b_status != 201 else self.b_url,
            "source_bytes": len(data), "source_sha256": SHA_B,
            "receipt": {"uploaded": []},
        }

    def download(self, url):
        sha = SHA_A if url.startswith("/files/a") else SHA_B
        return {"status": 200, "sha256": sha, "bytes": 64}

    def list_files(self):
        return {"rows": [{"name": n, "size": 64} for n in self._names]}


def _run_entry(framework_root, fake):
    spec = importlib.util.spec_from_file_location(
        "fileqa_f04_entry", framework_root / "tests" / "e2e" / "test_collision.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_f04_collision(
        fake,
        run_id="t10",
        profile={"policy": {"collision": "unknown"}},
        record={},
        record_upload=lambda up: None,
    )


@pytest.mark.parametrize("status", [500, 400])
def test_entry_server_or_foreign_client_error_fails(framework_root, status):
    with pytest.raises(AssertionError, match="F04"):
        _run_entry(framework_root, _FakeClient(b_status=status, b_url=None))


def test_entry_transport_error_fails(framework_root):
    import httpx

    with pytest.raises(AssertionError, match="F04"):
        _run_entry(framework_root, _FakeClient(b_error=httpx.ConnectError("synthetic")))


def test_entry_accepted_without_url_fails(framework_root):
    with pytest.raises(AssertionError, match="F04"):
        _run_entry(framework_root, _FakeClient(b_status=201, b_url=None))


def test_entry_correct_b_passes(framework_root):
    _run_entry(framework_root, _FakeClient(b_status=201, b_url="/files/b"))


def test_entry_conflict_409_passes(framework_root):
    _run_entry(framework_root, _FakeClient(b_status=409, b_url=None))
