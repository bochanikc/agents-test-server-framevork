"""C01 — квота количества объектов (N).

На чистом namespace: 7 коротких объектов, 8-й принят, 9-й отклонён.
Проверяются список, SHA ранее принятых и неизменность счётчика после отказа.
"""

import pytest

from fileqa.digest import sha256
from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.capacity
def test_c01_object_count_quota(stand, helpers):
    base = helpers.preamble("C01", count=True)
    N = stand.limits["object_count"]
    if base["count"] != 0:
        helpers.skip(
            "C01",
            f"нужен чистый namespace: исходно {base['count']} объектов / {base['bytes']} байт",
        )

    payload_size = 4
    single = stand.limits.get("single_file_bytes")
    if single is not None and payload_size > single:
        helpers.skip(
            "C01",
            f"короткий объект {payload_size} байт больше limits.single_file_bytes={single}",
        )

    journal = []
    accepted = []

    def put(seed):
        name = unique_name(run_id=stand.run_id, prefix="c01", suffix=".bin")
        data = binary_payload(payload_size, seed=seed)
        r = stand.client.upload(name, data)
        journal.append({"name": name, "source_bytes": len(data),
                        "status": r["status"], "receipt": r.get("receipt")})
        return name, data, r

    # подготовка N-1 коротких объектов
    for i in range(N - 1):
        name, data, r = put(i)
        assert r["status"] == 201, (name, r["status"], r.get("receipt"))
        accepted.append({"name": name, "bytes": len(data),
                         "sha256": sha256(data), "url": r["url"]})

    # N-й объект — принимается
    name_n, data_n, rn = put(N)
    assert rn["status"] == 201, (name_n, rn["status"], rn.get("receipt"))
    accepted.append({"name": name_n, "bytes": len(data_n),
                     "sha256": sha256(data_n), "url": rn["url"]})

    # N+1-й объект — отказ
    name_over, data_over, rover = put(N + 1)
    assert helpers.is_rejected(rover["status"]), (name_over, rover["status"], rover.get("receipt"))

    names = {o["name"] for o in accepted}
    _, rows = helpers.list_rows()
    own = [r for r in rows if r.get("name") in names]
    assert len(own) == N, f"ожидалось {N} своих записей, в списке {len(own)}"
    size_by_name = {o["name"]: o["bytes"] for o in accepted}
    assert all(r.get("size") == size_by_name[r["name"]] for r in own)

    # отказ не добавил записи
    assert not any(r.get("name") == name_over for r in rows)

    # SHA ранее принятых объектов не изменились
    for o in accepted:
        ck = helpers.fetch_check(o["url"], o["sha256"], o["bytes"])
        assert ck["sha_ok"] and ck["size_ok"], (o["name"], ck)

    # счётчик не изменился после отказа
    _, rows_after = helpers.list_rows()
    own_after = [r for r in rows_after if r.get("name") in names]
    assert len(own_after) == N

    helpers.record(
        "C01",
        status="pass",
        object_count_limit=N,
        accepted=len(accepted),
        rejected_status=rover["status"],
        list_own_after_reject=len(own_after),
        journal=journal,
        control_sha={o["name"]: o["sha256"] for o in accepted},
    )
