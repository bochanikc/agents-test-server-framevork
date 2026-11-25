"""F04 — последовательное сохранение A и B под одним именем.

Оракул обязан увидеть все три согласованных исхода (replace / versioned /
reject) и, при неизвестной политике, распознать доказанное расхождение
квитанции со скачанными байтами: если квитанция B принята (2xx) и выдала
ссылку, чтение по этой ссылке обязано вернуть байты B. Возврат A по ссылке,
обещавшей B, — дефект. Маскирования через retry или постоянный xfail нет.
"""

import pytest

from fileqa.config import policy_of
from fileqa.digest import sha256
from fileqa.fixtures import binary_payload, unique_name


# Ожидаемый конфликт имени. Для локального дублёра и согласованного контракта
# это 409; прочие 4xx (400, 404, 413) — не «ожидаемый отказ», а посторонняя
# клиентская ошибка, и проверку они проваливают.
CONFLICT_STATUSES = (409,)


def _is_2xx(status) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def _is_conflict(status) -> bool:
    return isinstance(status, int) and status in CONFLICT_STATUSES


def _transport_failed(up_b: dict) -> bool:
    """Нет HTTP-ответа: статус None/0 либо явная транспортная ошибка."""
    status = up_b.get("status")
    return status in (None, 0)


def _url_of(up: dict) -> str | None:
    url = up.get("url")
    return url if isinstance(url, str) and url.strip() else None


def _reads_are(reads: list, status: int, sha: str) -> bool:
    return bool(reads) and all(r.get("status") == status and r.get("sha256") == sha for r in reads)


def _rejection_detail(up_b: dict) -> str:
    status = up_b.get("status")
    if _transport_failed(up_b):
        err = up_b.get("error") or "нет ответа"
        return f"B: транспортная ошибка ({err})"
    if isinstance(status, int) and status >= 500:
        return f"B: серверная ошибка {status}"
    return f"B: посторонний отказ {status} (ожидался только конфликт имени 409)"


def _f04_oracle(policy, up_a, up_b, read_before, reads_a, reads_b, matches):
    """Возвращает (verdict, detail); verdict в {pass, fail}.

    Допустимый отказ B — только согласованный конфликт имени (409).
    HTTP 5xx, отсутствие ответа и посторонние 4xx проваливают проверку.
    Принятый B обязан иметь собственный url в квитанции; ссылка A не
    подставляется. Полученные байты сверяются с SHA-256 редакции B.
    """
    sha_a = up_a["source_sha256"]
    sha_b = up_b["source_sha256"]

    # 1. A до изменения обязано читаться как A.
    if read_before.get("status") != 200 or read_before.get("sha256") != sha_a:
        return "fail", (
            f"A не читается до изменения: status={read_before.get('status')} "
            f"sha={read_before.get('sha256')}"
        )

    if not matches:
        return "fail", "своя запись не найдена в списке после операций"

    status = up_b.get("status")
    b_accepted = _is_2xx(status)
    b_conflict = _is_conflict(status)
    sizes = {m.get("size") for m in matches}

    # 2. Отказ B допустим только как конфликт имени. Всё остальное — fail.
    if not b_accepted and not b_conflict:
        return "fail", _rejection_detail(up_b)

    url_a = _url_of(up_a)
    url_b = _url_of(up_b)

    if b_accepted and not url_b:
        return "fail", f"квитанция B принята ({status}), но не содержит пригодного url"

    if not b_accepted:
        # Конфликт: A обязана сохраниться, лишней записи быть не должно.
        if len(matches) != 1 or sizes != {up_a["source_bytes"]}:
            return "fail", (
                "после конфликта B запись списка не равна одной редакции A: "
                f"строк {len(matches)}, размеры {sorted(s for s in sizes if s is not None)}"
            )
        if not _reads_are(reads_a, 200, sha_a):
            return "fail", "после конфликта B ссылка A не отдаёт байты A"
        return "pass", f"{policy}: B отклонён конфликтом {status}, A сохранена"

    if policy == "reject":
        return "fail", f"reject: ожидался конфликт B (409), получено {status}"

    if policy == "versioned":
        if not url_a:
            return "fail", "versioned: у квитанции A нет url"
        if url_a == url_b:
            return "fail", "versioned: A и B получили один url — редакции не различить"
        if not _reads_are(reads_b, 200, sha_b):
            return "fail", "versioned: ссылка B не отдаёт байты B"
        if not _reads_are(reads_a, 200, sha_a):
            return "fail", "versioned: ссылка A не отдаёт байты A"
        if not {up_a["source_bytes"], up_b["source_bytes"]} <= sizes:
            return "fail", "versioned: в списке нет обеих редакций"
        return "pass", "versioned: A → A, B → B, обе редакции в списке"

    if policy == "replace":
        if not _reads_are(reads_b, 200, sha_b):
            return "fail", "replace: ссылка B не отдаёт байты B"
        if up_b["source_bytes"] not in sizes:
            return "fail", "replace: запись списка не соответствует B"
        if url_a == url_b and not _reads_are(reads_a, 200, sha_b):
            return "fail", "replace: общая ссылка не отдаёт B после замены"
        return "pass", "replace: имя указывает на B"

    # unknown — политика не названа; проверяем согласованность квитанции и выдачи.
    b_shas = {r.get("sha256") for r in reads_b}
    b_statuses = {r.get("status") for r in reads_b}
    if len(b_shas) > 1 or len(b_statuses) > 1:
        return "fail", "unknown: ссылка B возвращает разные байты/статусы при повторных чтениях"
    if not _reads_are(reads_b, 200, sha_b):
        got = b_shas.pop() if len(b_shas) == 1 else None
        if got == sha_a:
            return "fail", "unknown: квитанция обещает B, ссылка B возвращает A (устаревшая редакция)"
        return "fail", f"unknown: квитанция обещает B, ссылка B возвращает иные байты (sha {got})"
    if up_b["source_bytes"] not in sizes:
        return "fail", "unknown: принятый B не отражён размером в списке"
    return "pass", "unknown: ссылка B согласованно возвращает B (B/B/B)"


@pytest.mark.e2e
def test_f04_collision(client, run_id, profile, record, record_upload):
    """F04 по нескольким независимым именам: дефект имя-зависим, одно имя может
    попасть на «хорошее» и дать ложный pass. Требуем pass по всем именам."""
    record["case_id"] = "F04"

    size = 64
    policy = policy_of(profile)["collision"]
    trials = []

    for i in range(3):
        name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")
        data_a = binary_payload(size, seed=1)
        data_b = binary_payload(size, seed=2)
        assert data_a != data_b
        sha_a = sha256(data_a)
        sha_b = sha256(data_b)

        up_a = client.upload(name, data_a)
        record_upload(up_a)
        if not (200 <= up_a["status"] < 300) or not up_a.get("url"):
            pytest.skip(
                f"F04: A не принят (status={up_a['status']}), сценарий неприменим"
            )

        read_before = client.download(up_a["url"])
        try:
            up_b = client.upload(name, data_b)
        except Exception as exc:  # транспортная ошибка — это не допустимый отказ
            up_b = {
                "status": None,
                "url": None,
                "receipt": None,
                "source_bytes": len(data_b),
                "source_sha256": sha_b,
                "error": f"{type(exc).__name__}: {exc}",
            }
        record_upload(up_b)

        # Ссылку B не подставляем из квитанции A: принятый B обязан иметь свой url.
        url_b = up_b.get("url")
        reads_b = [client.download(url_b) for _ in range(3)] if url_b else []
        reads_a = [client.download(up_a["url"]) for _ in range(3)]

        lst = client.list_files()
        saved_names = {n for n in (up_a.get("name"), up_b.get("name")) if n}
        matches = [r for r in (lst["rows"] or []) if r.get("name") in saved_names]

        verdict, detail = _f04_oracle(
            policy, up_a, up_b, read_before, reads_a, reads_b, matches
        )
        trials.append(
            {
                "name": name,
                "sha_a": sha_a,
                "sha_b": sha_b,
                "receipt_a": up_a["receipt"],
                "receipt_b": up_b["receipt"],
                "url_a": up_a.get("url"),
                "url_b": up_b.get("url"),
                "read_before": {
                    "status": read_before["status"],
                    "bytes": read_before["bytes"],
                    "sha256": read_before["sha256"],
                },
                "reads": {
                    "url_a": [
                        {"status": r["status"], "bytes": r["bytes"], "sha256": r["sha256"]}
                        for r in reads_a
                    ],
                    "url_b": [
                        {"status": r["status"], "bytes": r["bytes"], "sha256": r["sha256"]}
                        for r in reads_b
                    ],
                },
                "list_matches": matches,
                "verdict": verdict,
                "detail": detail,
            }
        )

    # Три независимых имени обязательны: одно имя может дать ложный pass.
    assert len(trials) == 3, f"F04: проверено {len(trials)} имён вместо 3"
    failed = [t for t in trials if t["verdict"] != "pass"]
    record["policy"] = policy
    record["names_checked"] = len(trials)
    record["names_passed"] = len(trials) - len(failed)
    record["trials"] = trials
    record["verdict"] = "fail" if failed else "pass"
    record["detail"] = (
        "; ".join(f"{t['name']}: {t['detail']}" for t in failed)
        if failed
        else "все независимые имена прошли"
    )

    assert not failed, f"F04: {record['detail']}"
