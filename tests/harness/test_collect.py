"""Самопроверка решения по прогону: обязательные кейсы берутся из профиля.

R2-099: жёсткий список H01/L01/F01 больше не решает GO. Отсутствие
обязательного кейса и его статусы skip / incomplete / observation блокируют
GO так же, как fail даёт NO-GO. Проверяется сборщик карточек и валидатор
отчёта — обе точки, где решение может стать зелёным без оснований.
"""

import importlib.util
import json
from pathlib import Path

import pytest


def _load(framework_root: Path, name: str):
    spec = importlib.util.spec_from_file_location(
        f"fileqa_tool_{name}", framework_root / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def collect_mod(framework_root):
    return _load(framework_root, "collect")


@pytest.fixture
def report_mod(framework_root):
    return _load(framework_root, "report")


def _card(case_id: str, status: str) -> dict:
    return {
        "source": "02-e2e",
        "run_id": "run-test",
        "case_id": case_id,
        "utc": "2026-11-25T00:00:00Z",
        "status": status,
    }


def _run(tmp_path: Path, cards: list[dict], manifest: dict | None = None) -> Path:
    run = tmp_path / "run"
    (run / "e2e").mkdir(parents=True)
    for card in cards:
        (run / "e2e" / f"{card['case_id']}.json").write_text(
            json.dumps(card), encoding="utf-8"
        )
    if manifest is not None:
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def _profile(*required: str) -> dict:
    return {"name": "test", "required": {"cases": list(required)}}


def test_go_when_all_profile_cases_pass(collect_mod, tmp_path):
    run = _run(tmp_path, [_card("H01", "pass"), _card("L01", "pass")])
    data = collect_mod.collect(run, profile=_profile("H01", "L01"))
    assert data["decision"] == "GO"
    assert data["required"] == ["H01", "L01"]


def test_profile_overrides_default_hardcode(collect_mod, tmp_path):
    # F02 проходит, H01/L01 отсутствуют: решение обязано опираться на профиль.
    run = _run(tmp_path, [_card("F02", "pass")])
    data = collect_mod.collect(run, profile=_profile("F02"))
    assert data["decision"] == "GO"
    assert data["required"] == ["F02"]


@pytest.mark.parametrize("status", ["observation", "skip", "incomplete"])
def test_required_non_pass_blocks_go(collect_mod, tmp_path, status):
    cards = [_card("H01", "pass"), _card("F02", "pass"), _card("F07", status)]
    run = _run(tmp_path, cards)
    data = collect_mod.collect(run, profile=_profile("H01", "F02", "F07"))
    assert data["decision"] == "HOLD"
    assert "F07" in data["reason"]


def test_missing_required_blocks_go(collect_mod, tmp_path):
    run = _run(tmp_path, [_card("H01", "pass")])
    data = collect_mod.collect(run, profile=_profile("H01", "F07"))
    assert data["decision"] == "HOLD"
    assert "F07" in data["reason"]


def test_empty_required_does_not_make_go(collect_mod, tmp_path):
    run = _run(tmp_path, [_card("H01", "pass")])
    data = collect_mod.collect(run, profile=_profile())
    assert data["decision"] == "HOLD"
    assert "required.cases" in data["reason"]


def test_manifest_required_cases_used_without_profile(collect_mod, tmp_path):
    run = _run(
        tmp_path,
        [_card("F02", "pass")],
        manifest={"origin": "http://files.example.com", "required_cases": ["F02"]},
    )
    data = collect_mod.collect(run)
    assert data["decision"] == "GO"
    assert data["required"] == ["F02"]


def test_fail_is_no_go_even_with_required_pass(collect_mod, tmp_path):
    run = _run(tmp_path, [_card("F02", "pass"), _card("F04", "fail")])
    data = collect_mod.collect(run, profile=_profile("F02"))
    assert data["decision"] == "NO-GO"


def _results(required: list[str], evidence: Path) -> dict:
    return {
        "title": "t",
        "service": "s",
        "target": "http://files.example.com",
        "period": "2026-11-25",
        "environment": "live",
        "decision": "GO",
        "reason": "ok",
        "next": "none",
        "required": required,
        "cases": [
            {
                "id": "H01",
                "title": "health",
                "status": "pass",
                "steps": "GET /health",
                "expected": "200",
                "actual": "200",
                "repro": "python3 -m pytest tests/e2e/test_health_list.py::test_h01_health -m e2e",
                "evidence": [evidence.name],
            }
        ],
        "questions": [],
        "gaps": [],
        "attribution": ["test"],
    }


def test_report_go_checks_profile_required(report_mod, tmp_path):
    (tmp_path / "card.json").write_text("{}", encoding="utf-8")
    report_mod.validate(tmp_path, _results(["H01"], tmp_path / "card.json"))
    with pytest.raises(ValueError, match="F07"):
        report_mod.validate(tmp_path, _results(["H01", "F07"], tmp_path / "card.json"))
