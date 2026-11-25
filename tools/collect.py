"""Агрегатор карточек ролей в results.json схемы report.py.

`make report RUN=<run-id>` вызывает `tools/report.py artifacts/<run-id>`,
которому нужен `results.json` в схеме `title/service/target/period/environment/
decision/cases[…]/questions/gaps/attribution`. Роли пишут карточки `new_case`
(формат `{source, run_id, case_id, utc, …}`) в `artifacts/<run-id>/<role>/*.json`.
Этот адаптер собирает их в `results.json` и дополняет недостающие поля.

Решение вычисляется честно по карточкам: подтверждённый дефект (`outcome=failed`
с реальным assert) → NO-GO; отсутствие обязательного кейса или его статус
skip/incomplete/observation → HOLD; иначе GO. Обязательные кейсы берутся из
`required.cases` профиля (аргумент `--profile`), затем из поля
`required_cases` манифеста; жёсткий список H01/L01/F01 остаётся только
запасным вариантом, когда ни профиля, ни манифеста нет. k6-сводку и
окончательную причину решения оркестратор уточняет после прогона.

Использование: python3 tools/collect.py artifacts/<run-id> [--profile profiles/live.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fileqa.config import load_profile, required_cases_of

SUITES = {
    "H": "e2e", "L": "e2e", "F": "e2e", "N": "e2e",
    "C": "capacity",
    "SEC": "security",
}

# case_id -> (pytest-путь к тесту, человеческий заголовок, серьёзность при fail).
NODES = {
    "H01": ("tests/e2e/test_health_list.py::test_h01_health", "Health: liveness", "High"),
    "L01": ("tests/e2e/test_health_list.py::test_l01_list", "Список: своя запись видна", "High"),
    "F01": ("tests/e2e/test_upload.py::test_f01_roundtrip", "Загрузка → список → скачивание, SHA", "High"),
    "F02": ("tests/e2e/test_upload.py::test_f02_empty", "Пустой файл", "Medium"),
    "F03": ("tests/e2e/test_upload.py::test_f03_cyrillic_space", "Имя с кириллицей и пробелом", "Medium"),
    "F04": ("tests/e2e/test_collision.py::test_f04_collision", "Повтор имени A→B", "High"),
    "F05": ("tests/e2e/test_delete.py::test_f05_delete", "Удаление записи", "Medium"),
    "F06": ("tests/e2e/test_limits.py::test_f06_size_boundary", "Границы размера", "High"),
    "F07": ("tests/e2e/test_batch.py::test_f07_batch_receipt", "Полнота пакетной квитанции", "High"),
    "N01": ("tests/e2e/test_negative.py::test_n01_form_without_file", "Форма без файла", "Medium"),
    "N02": ("tests/e2e/test_negative.py::test_n02_missing_file", "Отсутствующее имя", "Medium"),
    "C01": ("tests/capacity/test_c01.py::test_c01_object_count_quota", "Квота количества", "High"),
    "C02": ("tests/capacity/test_c02.py::test_c02_logical_bytes_quota", "Квота суммы байтов", "High"),
    "C03": ("tests/capacity/test_c03.py::test_c03_change_accounting", "Учёт изменений", "Medium"),
    "C04": ("tests/capacity/test_c04.py::test_c04_catalog_size", "Размер каталога", "Medium"),
    "C05": ("tests/capacity/test_c05.py::test_c05_actual_capacity_forecast", "Фактическая ёмкость", "Medium"),
    "SEC01": ("tests/security/test_transport.py::test_transport_scheme_and_credentials", "Транспорт и учётные данные", "Medium"),
    "SEC02": ("tests/security/test_delivery.py::test_attachment_headers_and_name", "Заголовки выдачи", "Medium"),
    "SEC03": ("tests/security/test_public_schema.py::test_public_schema_no_internal_path", "Внутренний путь в публичной схеме", "Medium"),
    "SEC04": ("tests/security/test_diagnostics.py::test_error_bodies_minimal", "Минимальность тел ошибок", "Medium"),
    "SEC05": ("tests/security/test_hygiene.py::test_synthetic_secret_absent_from_artifacts", "Гигиена секретов", "Low"),
    "SEC06": ("tests/security/test_configuration.py::test_configuration_declared_or_question", "Конфигурация vs профиль", "Low"),
}

# Только запасной вариант, когда профиль и манифест не переданы.
DEFAULT_REQUIRED = ("H01", "L01", "F01")


def required_cases(profile: dict | None = None, manifest: dict | None = None) -> list:
    """Обязательные кейсы: профиль → манифест → запасной список."""
    if profile is not None:
        return required_cases_of(profile)
    if manifest and isinstance(manifest.get("required_cases"), list):
        return [str(x).strip() for x in manifest["required_cases"] if str(x).strip()]
    return list(DEFAULT_REQUIRED)


def _status(card: dict) -> str:
    """Статус карточки: pass / fail / observation / skip / incomplete."""
    if card.get("status") in ("pass", "fail", "observation", "skip", "incomplete"):
        return card["status"]
    if card.get("incomplete"):
        return "incomplete"
    outcome = card.get("outcome")
    if outcome == "passed":
        return "pass"
    if outcome == "failed":
        return "fail"
    if outcome == "skipped":
        return "skip"
    return "observation"


def _repro(case_id: str, suite: str) -> str:
    node = NODES.get(case_id, (None, None, None))[0]
    if node:
        return f"python3 -m pytest {node} -m {SUITES.get(case_id[0], 'e2e')}"
    return f"python3 -m pytest tests/{suite} -m {suite}"


def collect(run_dir: Path, profile: dict | None = None) -> dict:
    cards = []
    for role in ("e2e", "capacity", "security"):
        role_dir = run_dir / role
        if not role_dir.is_dir():
            continue
        for f in sorted(role_dir.glob("*.json")):
            try:
                cards.append(json.loads(f.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue

    manifest = {}
    mf = run_dir / "manifest.json"
    if mf.is_file():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            manifest = {}

    cases, gaps, questions = [], [], []
    for card in cards:
        case_id = card.get("case_id") or ""
        status = _status(card)
        if status == "incomplete":
            gaps.append(f"{case_id}: {card.get('reason') or 'не завершено'}")
            continue
        if status == "skip":
            gaps.append(f"{case_id}: {card.get('reason') or 'нет стенда/возможности'}")
            continue

        node, title, severity = NODES.get(case_id, (None, case_id or "?", "Medium"))
        suite = SUITES.get((case_id or "?")[0], "e2e")
        detail = card.get("detail") or card.get("reason") or ""

        case = {
            "id": case_id,
            "title": title,
            "status": status,
            "steps": card.get("steps") or f"Сценарий {case_id} (роль {card.get('source', '?')}); см. evidence.",
            "expected": card.get("expected") or "Согласованный контракт профиля/coverage.md.",
            "actual": detail or card.get("actual") or ("Проверка прошла." if status == "pass" else "Проверка не прошла."),
            "repro": card.get("repro") or _repro(case_id, suite),
            "evidence": [str(Path(card.get("_path", "")).relative_to(run_dir))
                         if card.get("_path") else f"{suite}/{case_id}.json"],
        }
        if status == "fail":
            case["severity"] = card.get("severity") or severity
            case["impact"] = card.get("impact") or (detail or f"Сценарий {case_id} не выполнен.")
            case["acceptance"] = card.get("acceptance") or f"Повторить {case_id} после исправления и получить ожидаемый результат."
        cases.append(case)

    if not cases:
        cases.append({
            "id": "NO-RUN",
            "title": "Нет карточек для прогона",
            "status": "observation",
            "steps": "Соберите карточки ролей в artifacts/<run-id>/<role>/.",
            "expected": "Наличие карточек после прогона.",
            "actual": "Карточки не найдены.",
            "repro": "make e2e PROFILE=live",
            "evidence": [],
        })

    passed = {c["id"] for c in cases if c["status"] == "pass"}
    failed = [c for c in cases if c["status"] == "fail"]
    required = required_cases(profile, manifest)
    unconfirmed = [case_id for case_id in required if case_id not in passed]

    if failed:
        first = failed[0]
        decision, reason = "NO-GO", f"{first['id']}: {first['actual']}"
    elif not required:
        decision, reason = "HOLD", "профиль не задаёт обязательные кейсы (required.cases)"
    elif unconfirmed:
        decision, reason = "HOLD", (
            "обязательные кейсы не подтверждены: " + ", ".join(unconfirmed)
        )
    elif gaps:
        decision, reason = "HOLD", "есть пропущенные/незавершённые проверки: " + "; ".join(gaps[:3])
    else:
        decision, reason = "GO", "обязательные сценарии пройдены"

    for q in manifest.get("questions", []):
        if isinstance(q, str) and q.strip():
            questions.append(q)

    return {
        "title": "Приёмка файлового API",
        "service": "Сервис приёма/выдачи файлов (чёрный ящик)",
        "target": manifest.get("origin", "unknown"),
        "period": manifest.get("utc", "unknown"),
        "environment": manifest.get("environment_type", "live"),
        "decision": decision,
        "reason": reason,
        "required": required,
        "next": "См. coverage.md и review-queue.",
        "cases": cases,
        "questions": questions,
        "gaps": gaps,
        "attribution": ["Собрано tools/collect.py из карточек ролей (source/run-id/case-id)."],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка results.json из карточек ролей.")
    parser.add_argument("run", type=Path, help="каталог прогона artifacts/<run-id>")
    parser.add_argument(
        "--profile",
        help="профиль с required.cases; без него берётся required_cases манифеста",
    )
    args = parser.parse_args(argv)
    run_dir = args.run.resolve()
    profile = load_profile(args.profile) if args.profile else None
    data = collect(run_dir, profile=profile)
    out = run_dir / "results.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
