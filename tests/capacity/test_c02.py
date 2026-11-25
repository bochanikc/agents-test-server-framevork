"""C02 — квота суммы логических байтов (B).

16384 + 16383 байт (B−1), затем +1 байт (B), затем ещё +1 (B+1, отказ).
Сверяются сумма принятых байтов, отказ без лишней записи и доступность прежних.
"""

import pytest

from fileqa.digest import sha256
from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.capacity
def test_c02_logical_bytes_quota(stand, helpers):
    base = helpers.preamble("C02", bytes_=True)
    B = stand.limits["logical_bytes"]
    if B is None:
        helpers.skip("C02", "limits.logical_bytes не задан")
    if B < 3:
        helpers.skip("C02", f"B={B} слишком мал для границы B−1/B/B+1")
    if base["bytes"] != 0 or base["count"] != 0:
        helpers.skip(
            "C02",
            f"нужен чистый namespace: исходно {base['count']} объектов / {base['bytes']} байт",
        )

    # Размеры выводятся из B: first + second = B−1, затем +1 = B, ещё +1 = B+1.
    first = B // 2
    second = B - first - 1

    single = stand.limits.get("single_file_bytes")
    for sz in (first, second, 1):
        if single is not None and sz > single:
            helpers.skip("C02", f"файл {sz} байт больше limits.single_file_bytes={single}")

    journal = []
    accepted = []

    def put(seed, size):
        name = unique_name(run_id=stand.run_id, prefix="c02", suffix=".bin")
        data = binary_payload(size, seed=seed)
        r = stand.client.upload(name, data)
        journal.append({"name": name, "source_bytes": size,
                        "status": r["status"], "receipt": r.get("receipt")})
        return name, data, r

    # B−1
    n1, d1, r1 = put(1, first)
    n2, d2, r2 = put(2, second)
    assert r1["status"] == 201 and r2["status"] == 201, (r1["status"], r2["status"])
    accepted.extend([
        {"name": n1, "bytes": first, "sha256": sha256(d1), "url": r1["url"]},
        {"name": n2, "bytes": second, "sha256": sha256(d2), "url": r2["url"]},
    ])

    # B (граница)
    n3, d3, r3 = put(3, 1)
    assert r3["status"] == 201, (r3["status"], r3.get("receipt"))
    accepted.append({"name": n3, "bytes": 1, "sha256": sha256(d3), "url": r3["url"]})

    # B+1 — отказ
    n4, d4, r4 = put(4, 1)
    assert helpers.is_rejected(r4["status"]), (r4["status"], r4.get("receipt"))

    total = sum(o["bytes"] for o in accepted)
    assert total == B, (total, B)

    names = {o["name"] for o in accepted}
    _, rows = helpers.list_rows()
    own = [r for r in rows if r.get("name") in names]
    assert len(own) == 3, f"ожидалось 3 записи, в списке {len(own)}"
    assert not any(r.get("name") == n4 for r in rows)

    for o in accepted:
        ck = helpers.fetch_check(o["url"], o["sha256"], o["bytes"])
        assert ck["sha_ok"] and ck["size_ok"], (o["name"], ck)

    helpers.record(
        "C02",
        status="pass",
        logical_bytes_limit=B,
        accepted_bytes_total=total,
        rejected_status=r4["status"],
        accepted_objects=len(accepted),
        journal=journal,
        control_sha={o["name"]: o["sha256"] for o in accepted},
    )
