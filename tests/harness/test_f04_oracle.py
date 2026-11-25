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
