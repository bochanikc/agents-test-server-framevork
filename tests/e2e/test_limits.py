"""F06 — граница размера одной multipart-части: L-1, L, L+1.

Принятые объекты сверяются по длине и SHA. После отказа (413) проверяется
отсутствие новой записи и сохранность контрольных файлов (принятые L-1 и L).
Размер переданной файловой части регистрируется независимо от длины
HTTP-конверта (поле `source_bytes` у клиента).

Отдельная подпроверка R2-006: предел применяется к части, а не ко всему телу
запроса. Пакет из двух допустимых частей по 614 400 Б даёт тело больше
1 МиБ — он должен быть принят целиком, с двумя квитанциями и двумя выдачами.
Текст 413 при этом не требуется менять; фиксируются content-type и тело.
"""

import pytest

from fileqa.config import limits_of
from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.e2e
def test_f06_size_boundary(client, run_id, profile, record, record_upload):
    record["case_id"] = "F06"

    L = limits_of(profile)["single_file_bytes"]
    if L is None:
        record["reason"] = "профиль не задаёт лимит одного файла (single_file_bytes)"
        pytest.skip("профиль не задаёт лимит одного файла (single_file_bytes)")

    sizes = {"under": L - 1, "at": L, "over": L + 1}
    seeds = {"under": 6, "at": 7, "over": 8}

    results = {}
    for label, size in sizes.items():
        name = unique_name(run_id=run_id, prefix=f"qa-{label}", suffix=".bin")
        data = binary_payload(size, seed=seeds[label])
        up = client.upload(name, data)
        results[label] = {
            "name": name,
            "size": size,
            "source_bytes": up["source_bytes"],  # размер файловой части, не конверта
            "source_sha256": up["source_sha256"],
            "status": up["status"],
            "url": up.get("url"),
            "receipt": up["receipt"],
            "request_bytes": up.get("request_bytes"),
            "content_type": up["headers"].get("content-type"),
            "error": up.get("error"),
        }
        if 200 <= up["status"] < 300:
            record_upload(up)

    # Принятые объекты: L-1 и L сверяем по длине и SHA.
    for label in ("under", "at"):
        r = results[label]
        assert 200 <= r["status"] < 300, (
            f"F06: {label} (size={r['size']}) отклонён: {r['status']}"
        )
        lst = client.list_files()
        own = [x for x in (lst["rows"] or []) if x.get("name") == r["name"]]
        assert own and own[0].get("size") == r["size"], (
            f"F06: запись списка {label} не сходится по размеру"
        )
        dl = client.download(r["url"])
        assert dl["status"] == 200, f"F06: скачивание {label} вернуло {dl['status']}"
        assert dl["bytes"] == r["size"], f"F06: длина {label} не совпадает"
        assert dl["sha256"] == r["source_sha256"], f"F06: SHA {label} не совпадает"

    # Отказ: L+1 → 413. Текст не требуется менять, но формат и тело фиксируются:
    # пустое тело не даёт клиенту диагностики (R2-051).
    over = results["over"]
    assert over["status"] == 413, f"F06: L+1 должен дать 413, получено {over['status']}"
    assert over["error"], "F06: тело 413 пустое — текст отказа не зафиксирован"
    assert over["content_type"], "F06: 413 без content-type — формат отказа не зафиксирован"

    # Отсутствие новой записи после отказа.
    lst = client.list_files()
    names = {x.get("name") for x in (lst["rows"] or [])}
    assert over["name"] not in names, "F06: запись L+1 появилась после отказа"

    # Сохранность контрольных файлов после отказа.
    for label in ("under", "at"):
        r = results[label]
        dl = client.download(r["url"])
        assert dl["sha256"] == r["source_sha256"] and dl["bytes"] == r["size"], (
            f"F06: контрольный файл {label} изменён после отказа"
        )

    # R2-006: предел относится к части. Две допустимые части по 614 400 Б
    # дают тело запроса больше 1 МиБ и должны быть приняты обе.
    part = 614400
    batch = {"part_bytes": part, "request_body_limit": L, "applicable": 2 * part > L}
    if batch["applicable"]:
        names = [
            unique_name(run_id=run_id, prefix="qa-batch-a", suffix=".bin"),
            unique_name(run_id=run_id, prefix="qa-batch-b", suffix=".bin"),
        ]
        payloads = [binary_payload(part, seed=21), binary_payload(part, seed=22)]
        assert payloads[0] != payloads[1]
        up = client.upload_many(list(zip(names, payloads)))
        record_upload(up)
        batch.update(
            status=up["status"],
            request_bytes=up.get("request_bytes"),
            receipts_count=up.get("receipts_count"),
            items_matched_by=up.get("items_matched_by"),
            error=up.get("error"),
        )
        assert 200 <= up["status"] < 300, (
            f"F06: пакет 2×{part} Б (тело > {L}) отклонён: {up['status']}"
        )
        assert up["request_bytes"] > L, (
            f"F06: тело пакета {up['request_bytes']} не превышает заявленный предел {L}"
        )
        assert up["receipts_count"] == len(names), (
            f"F06: в квитанции {up['receipts_count']} записей вместо {len(names)}"
        )
        rows = (client.list_files()["rows"] or [])
        by_name = {r.get("name"): r for r in rows}
        for src, payload in zip(up["items"], payloads):
            receipt = src["receipt"]
            assert receipt, f"F06: нет квитанции для части {src['name_sent']}"
            assert receipt.get("size") == part, (
                f"F06: size квитанции {receipt.get('size')} вместо {part}"
            )
            assert receipt.get("name") in by_name, (
                f"F06: части {src['name_sent']} нет в списке"
            )
            assert by_name[receipt["name"]].get("size") == part, (
                "F06: size строки списка не совпадает с частью"
            )
            dl = client.download(receipt.get("url"))
            assert dl["status"] == 200, f"F06: выдача части вернула {dl['status']}"
            assert dl["bytes"] == part, "F06: длина выдачи части не совпадает"
            assert dl["sha256"] == src["source_sha256"], (
                f"F06: SHA части {src['name_sent']} не совпадает"
            )
    record["batch"] = batch
    record["limit"] = L
    record["results"] = results
