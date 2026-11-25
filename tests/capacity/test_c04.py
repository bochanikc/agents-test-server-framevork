"""C04 — размер каталога: один сценарий листинга на подготовленных снимках.

Снимки (16×64КиБ и 1024×1КиБ = по 1 МиБ логических данных) заранее загружены
владельцем и описаны манифестами в profile.catalog.snapshots. Один и тот же
сценарий листинга: полнота, отсутствие дублей/пропусков по манифесту, число
страниц, размер ответа, время до первой и последней страницы.

На live снимки недоступны → skip с указанием фактического размера набора.
"""

import pytest

from fileqa.manifest import load as load_manifest


@pytest.mark.capacity
def test_c04_catalog_size(stand, helpers):
    snapshots = (stand.profile.get("catalog") or {}).get("snapshots") or []

    if not snapshots:
        r, rows = helpers.list_rows()
        actual = {"count": len(rows),
                  "bytes": sum(int(x.get("size") or 0) for x in rows),
                  "list_status": r["status"]}
        helpers.record("C04", status="skip",
                       reason="снимки C04 недоступны (profile.catalog.snapshots пуст)",
                       actual_set=actual)
        pytest.skip(f"C04: снимки недоступны; фактический набор {actual['count']} объектов / {actual['bytes']} байт")

    results = []
    for snap in snapshots:
        m = load_manifest(snap["manifest"])
        r, rows = helpers.list_rows()
        rec = helpers.reconcile(rows, m["objects"])
        results.append({
            "id": snap.get("id"),
            "expected_objects": len(m["objects"]),
            "logical_bytes": sum(o["bytes"] for o in m["objects"]),
            "list_status": r["status"],
            "pages": 1,  # в наблюдаемом контракте список отдаётся одним ответом без пагинации
            "response_bytes": r["bytes"],
            "time_first_page_s": r["elapsed_s"],
            "time_last_page_s": r["elapsed_s"],
            "reconcile": rec,
        })
        assert rec["complete"], rec

    helpers.record("C04", status="pass", snapshots=results)
