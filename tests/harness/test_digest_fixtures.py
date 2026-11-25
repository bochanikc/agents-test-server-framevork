"""Самопроверка хеширования и фикстур."""

import hashlib

from fileqa.digest import is_hex_sha256, sha256, sha256_file
from fileqa.fixtures import binary_payload, unique_name


def test_sha256_matches_stdlib():
    data = b"hello\x00world\r\n"
    assert sha256(data) == hashlib.sha256(data).hexdigest()


def test_is_hex_sha256():
    assert is_hex_sha256("a" * 64)
    assert not is_hex_sha256("A" * 64)  # только нижний регистр
    assert not is_hex_sha256("a" * 63)
    assert not is_hex_sha256("g" * 64)


def test_sha256_file(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == sha256(b"abc")


def test_binary_payload_contains_nul_crlf():
    data = binary_payload(64)
    assert len(data) == 64
    assert b"\x00" in data
    assert b"\r\n" in data


def test_binary_payload_deterministic_and_distinct():
    assert binary_payload(64, seed=7) == binary_payload(64, seed=7)
    assert binary_payload(64, seed=7) != binary_payload(64, seed=8)


def test_unique_name_distinct():
    a = unique_name(run_id="run-a")
    b = unique_name(run_id="run-a")
    assert a != b
    assert a.startswith("qa-run-a-")
