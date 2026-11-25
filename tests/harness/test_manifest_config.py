"""Самопроверка схемы манифеста и профиля."""

import json

import pytest

from fileqa import manifest
from fileqa.config import load_profile, origin_of
from fileqa.manifest import create, add_object, validate


def _base():
    return create("run-test", "live", "http://example.com")


def test_manifest_roundtrip(tmp_path):
    m = _base()
    add_object(m, "a.bin", "a.bin", "/files/a.bin", 3, "a" * 64)
    validate(m)
    manifest.dump(m, tmp_path / "m.json")
    assert manifest.load(tmp_path / "m.json")["objects"][0]["bytes"] == 3


def test_manifest_rejects_bad_sha():
    m = _base()
    add_object(m, "a.bin", "a.bin", "/files/a.bin", 3, "not-a-sha")
    with pytest.raises(ValueError):
        validate(m)


def test_manifest_rejects_negative_bytes():
    m = _base()
    m["objects"].append(
        {"name_sent": "a", "name_saved": "a", "url": "/files/a", "bytes": -1, "sha256": "a" * 64}
    )
    with pytest.raises(ValueError):
        validate(m)


def test_manifest_rejects_missing_origin():
    m = _base()
    del m["origin"]
    with pytest.raises(ValueError):
        validate(m)


def test_profile_live_loads(framework_root):
    p = load_profile(framework_root / "profiles/live.json")
    assert p["name"] == "live"
    assert origin_of(p) == "http://files.example.com"


def test_profile_unknown_limits_stay_none(framework_root):
    p = load_profile(framework_root / "profiles/live.json")
    assert p["limits"]["object_count"] is None
    assert p["limits"]["logical_bytes"] is None
