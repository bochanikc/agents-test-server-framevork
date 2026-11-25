"""F07 — полнота пакетной квитанции и изоляция частей одного POST.

Один POST с N уникальных имён должен дать ровно N записей квитанции: каждая
часть — своё имя, свой size и свой SHA-256, каждая ссылка читается своими
байтами. Отдельный случай — две части одинаковой длины с разными байтами:
перепутать имя ↔ байты здесь проще всего, а размер как признак не помогает.
Размер 0 и 1 байт входят в набор: пустая часть не должна теряться.
"""

import pytest

from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.e2e
def test_f07_batch_receipt(client, run_id, record, record_upload):
    record["case_id"] = "F07"

    # 1. N уникальных имён, включая 0 и 1 байт.
    sizes = [0, 1, 37]
    names = [
        unique_name(run_id=run_id, prefix=f"qa-batch-{size}", suffix=".bin")
        for size in sizes
    ]
    payloads = [binary_payload(size, seed=30 + i) for i, size in enumerate(sizes)]
    up = client.upload_many(list(zip(names, payloads)))
    record_upload(up)

    assert 200 <= up["status"] < 300, f"F07: пакет отклонён ({up['status']})"
    assert up["receipts_count"] == len(names), (
        f"F07: в квитанции {up['receipts_count']} записей вместо {len(names)}"
    )
    assert len(set(names)) == len(names), "F07: имена в пакете не уникальны"

    rows = client.list_files()["rows"] or []
    by_name = {}
    for row in rows:
        by_name.setdefault(row.get("name"), []).append(row)

    parts = []
    for src in up["items"]:
        receipt = src["receipt"]
        assert receipt, f"F07: нет квитанции для части {src['name_sent']}"
        assert receipt.get("name") == src["name_sent"], (
            f"F07: квитанция назвала {receipt.get('name')} вместо {src['name_sent']}"
        )
        assert receipt.get("size") == src["source_bytes"], (
            f"F07: size {receipt.get('size')} вместо {src['source_bytes']}"
        )
        own_rows = by_name.get(src["name_sent"], [])
        assert len(own_rows) == 1, (
            f"F07: у имени {src['name_sent']} {len(own_rows)} строк списка вместо 1"
        )
        assert own_rows[0].get("size") == src["source_bytes"], (
            "F07: size строки списка не совпадает с частью"
        )
        dl = client.download(receipt.get("url"))
        assert dl["status"] == 200, f"F07: выдача части вернула {dl['status']}"
        assert dl["bytes"] == src["source_bytes"], (
            f"F07: длина выдачи {dl['bytes']} вместо {src['source_bytes']}"
        )
        assert dl["sha256"] == src["source_sha256"], (
            f"F07: SHA части {src['name_sent']} не совпадает"
        )
        parts.append(
            {
                "name_sent": src["name_sent"],
                "name_receipt": receipt.get("name"),
                "size": src["source_bytes"],
                "source_sha256": src["source_sha256"],
                "download_status": dl["status"],
                "download_bytes": dl["bytes"],
                "download_sha256": dl["sha256"],
                "url": receipt.get("url"),
            }
        )

    assert sorted(p["size"] for p in parts) == sorted(sizes), (
        "F07: набор размеров пакета не совпал с отправленным"
    )
    assert len([r for r in rows if r.get("name") in set(names)]) == len(names), (
        "F07: число строк списка по именам пакета не равно числу частей"
    )

    # 2. Одинаковая длина у двух частей — отдельный случай: размер не различает
    #    записи, соответствие обязано сохраниться по имени.
    pair_names = [
        unique_name(run_id=run_id, prefix="qa-eqlen-a", suffix=".bin"),
        unique_name(run_id=run_id, prefix="qa-eqlen-b", suffix=".bin"),
    ]
    pair_payloads = [binary_payload(64, seed=41), binary_payload(64, seed=42)]
    assert pair_payloads[0] != pair_payloads[1]
    pair = client.upload_many(list(zip(pair_names, pair_payloads)))
    record_upload(pair)

    assert 200 <= pair["status"] < 300, f"F07: пара отклонена ({pair['status']})"
    assert pair["receipts_count"] == 2, (
        f"F07: в квитанции пары {pair['receipts_count']} записей вместо 2"
    )
    pair_parts = []
    for src in pair["items"]:
        receipt = src["receipt"]
        assert receipt, f"F07: нет квитанции для части {src['name_sent']}"
        assert receipt.get("name") == src["name_sent"], "F07: пара перепутала имена"
        assert receipt.get("size") == 64, "F07: size части пары не 64"
        dl = client.download(receipt.get("url"))
        assert dl["status"] == 200, f"F07: выдача пары вернула {dl['status']}"
        assert dl["bytes"] == 64, "F07: длина выдачи пары не 64"
        assert dl["sha256"] == src["source_sha256"], (
            f"F07: пара перепутала байты для {src['name_sent']}"
        )
        pair_parts.append(
            {
                "name_sent": src["name_sent"],
                "size": src["source_bytes"],
                "source_sha256": src["source_sha256"],
                "download_sha256": dl["sha256"],
                "url": receipt.get("url"),
                "path": receipt.get("path"),
            }
        )
    assert pair_parts[0]["url"] != pair_parts[1]["url"], "F07: у частей пары один url"
    assert pair_parts[0]["path"] != pair_parts[1]["path"], "F07: у частей пары один path"

    record["names_checked"] = len(names) + len(pair_names)
    record["batch"] = {
        "receipts_count": up["receipts_count"],
        "request_bytes": up.get("request_bytes"),
        "items_matched_by": up.get("items_matched_by"),
        "parts": parts,
    }
    record["equal_length_pair"] = pair_parts
