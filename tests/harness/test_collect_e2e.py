"""Сквозная регрессия T10: реальный pytest падает, отчёт обязан быть NO-GO.

Проверяется весь путь: pytest → junit.xml → tools/collect.py → tools/report.py.
Тест намеренно пишет карточку SEC02 со status=observation до assert False —
именно этот случай раньше давал ложный GO.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_pytest_failure_becomes_no_go(tmp_path, framework_root):
    run = tmp_path / "run"
    (run / "e2e").mkdir(parents=True)
    (run / "security").mkdir(parents=True)

    # Обязательный H01 подтверждён карточкой.
    (run / "e2e" / "H01.json").write_text(
        json.dumps(
            {
                "source": "02-e2e",
                "run_id": "t10-e2e",
                "case_id": "H01",
                "utc": "2026-11-25T00:00:00Z",
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )

    test_file = tmp_path / "test_guard_fail.py"
    test_file.write_text(
        """
import json
import os
from pathlib import Path


def test_sec02_guard(record_property):
    record_property("case_id", "SEC02")
    card_dir = Path(os.environ["QA_CARD_DIR"])
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "SEC02.json").write_text(json.dumps({
        "source": "05-security",
        "run_id": "t10-e2e",
        "case_id": "SEC02",
        "utc": "2026-11-25T00:00:00Z",
        "status": "observation",
    }))
    assert False, "synthetic security failure"
""",
        encoding="utf-8",
    )

    junit = run / "security" / "junit.xml"
    env = os.environ.copy()
    env["QA_CARD_DIR"] = str(run / "security")
    pytest_run = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), f"--junitxml={junit}", "-q"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert pytest_run.returncode == 1, pytest_run.stdout + pytest_run.stderr
    assert junit.is_file()

    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema": "fileqa-profile",
                "version": 1,
                "name": "t10",
                "origin": "http://127.0.0.1:9",
                "required": {"cases": ["H01"]},
            }
        ),
        encoding="utf-8",
    )

    collect = subprocess.run(
        [sys.executable, str(framework_root / "tools" / "collect.py"), str(run),
         "--profile", str(profile)],
        capture_output=True, text=True,
    )
    assert collect.returncode == 0, collect.stdout + collect.stderr
    data = json.loads((run / "results.json").read_text(encoding="utf-8"))
    assert data["decision"] == "NO-GO"
    sec = next(c for c in data["cases"] if c["id"] == "SEC02")
    assert sec["status"] == "fail"
    assert sec["evidence"] == ["security/junit.xml"]
    assert (run / sec["evidence"][0]).is_file()

    report = subprocess.run(
        [sys.executable, str(framework_root / "tools" / "report.py"), str(run)],
        capture_output=True, text=True,
    )
    assert report.returncode == 0, report.stdout + report.stderr
    page = (run / "report.html").read_text(encoding="utf-8")
    assert "NO-GO" in page
    assert "SEC02" in page
    assert (run / "developer.md").is_file()
