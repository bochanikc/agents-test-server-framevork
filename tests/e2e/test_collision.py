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


def _f04_oracle(policy, up_a, up_b, read_before, reads_a, reads_b, matches):
    """Возвращает (verdict, detail); verdict в {pass, fail}."""
    sha_a = up_a["source_sha256"]
    sha_b = up_b["source_sha256"]

    # 1. A до изменения обязано читаться как A.
    if read_before["status"] != 200 or read_before["sha256"] != sha_a:
        return "fail", (
            f"A не читается до изменения: status={read_before['status']} "
            f"sha={read_before['sha256']}"
        )

    if not matches:
        return "fail", "своя запись не найдена в списке после операций"

    b_accepted = 200 <= up_b["status"] < 300

    def _url_b_ok():
        return all(r["status"] == 200 and r["sha256"] == sha_b for r in reads_b)

    def _url_a_ok():
        return all(r["status"] == 200 and r["sha256"] == sha_a for r in reads_a)

    if policy == "reject":
        if b_accepted:
            return "fail", f"reject: ожидался отказ B (4xx), получено {up_b['status']}"
        if any(m.get("size") != up_a["source_bytes"] for m in matches):
            return "fail", "reject: запись списка не соответствует A"
        if not _url_a_ok():
            return "fail", "reject: A изменился после отклонённого B"
        return "pass", "reject: B отклонён (4xx), A сохранён"

    if policy == "versioned":
        if not b_accepted:
            return "fail", f"versioned: ожидалось принятие B, получено {up_b['status']}"
        if not _url_b_ok():
            return "fail", "versioned: ссылка B не отдаёт байты B"
        if not _url_a_ok():
            return "fail", "versioned: ссылка A не отдаёт байты A"
        return "pass", "versioned: A → A, B → B"

    if policy == "replace":
        if not b_accepted:
            return "fail", f"replace: ожидалось принятие B, получено {up_b['status']}"
        if any(m.get("size") != up_b["source_bytes"] for m in matches):
            return "fail", "replace: запись списка не соответствует B"
        if not _url_b_ok():
            return "fail", "replace: ссылка B не отдаёт байты B"
        if up_a["url"] == up_b["url"]:
            if not all(r["status"] == 200 and r["sha256"] == sha_b for r in reads_a):
                return "fail", "replace: общая ссылка не отдаёт B после замены"
        return "pass", "replace: имя указывает на B"

    # unknown — распознаём доказанное расхождение квитанции и выдачи.
    if b_accepted:
        b_shas = {r["sha256"] for r in reads_b}
        b_statuses = {r["status"] for r in reads_b}
        if len(b_shas) > 1 or len(b_statuses) > 1:
            return "fail", "unknown: ссылка B возвращает разные байты/статусы при повторных чтениях"
        got = b_shas.pop()
        st = b_statuses.pop()
        if st != 200:
            return "fail", f"unknown: квитанция обещает B, но ссылка B отвечает {st}"
        if got != sha_b:
            if got == sha_a:
                return "fail", "unknown: квитанция обещает B, ссылка B возвращает A (устаревшая редакция)"
            return "fail", f"unknown: квитанция обещает B, ссылка B возвращает иные байты (sha {got})"
        return "pass", "unknown: ссылка B согласованно возвращает B (B/B/B)"

    # B отклонён (4xx) — как reject: A обязан сохраниться.
    if not _url_a_ok():
        return "fail", "unknown: B отклонён, но A более не читается"
    return "pass", "unknown: B отклонён (4xx), A сохранён"


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
        up_b = client.upload(name, data_b)
        record_upload(up_b)

        url_b = up_b.get("url") or up_a.get("url")
        reads_b = [client.download(url_b) for _ in range(3)]
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
