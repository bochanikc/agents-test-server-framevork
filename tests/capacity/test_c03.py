"""C03 — учёт изменений: дельта замены, сумма версий, освобождение при удалении.

Работает только на подтверждённом стенде с квотами (reset/quotas/namespace).
На live (capabilities пусты) preamble уводит в skip «нужен управляемый стенд».
Удаление гейтится отдельно: маршрут DELETE не подтверждён в CONTRACT, а у
Client нет метода delete — поэтому под-проверка удаления регистрируется как
вопрос (incomplete), а не молча эмулируется.
"""

import pytest

from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.capacity
def test_c03_change_accounting(stand, helpers):
    base = helpers.preamble("C03")
    B = stand.limits["logical_bytes"]
    collision = stand.policy["collision"]

    if base["count"] != 0 or base["bytes"] != 0:
        helpers.skip(
            "C03",
            f"нужен чистый namespace: исходно {base['count']} объектов / {base['bytes']} байт",
        )
    if B is None:
        helpers.skip("C03", "limits.logical_bytes не задан — нечем измерять дельту/сумму")
    if collision not in ("replace", "versioned"):
        helpers.skip("C03", f"политика коллизий неизвестна/не replace-versioned ({collision})")

    journal = []
    sub = {}

    name = unique_name(run_id=stand.run_id, prefix="c03", suffix=".bin")

    if collision == "replace":
        # --- дельта размера при замене ---
        sizes = [16384, 32767, 32768, 32769]
        states = []
        url_32768 = None
        for seed, size in enumerate(sizes):
            data = binary_payload(size, seed=seed)
            r = stand.client.upload(name, data)
            journal.append({"name": name, "source_bytes": size,
                            "status": r["status"], "receipt": r.get("receipt")})
            states.append({"size": size, "status": r["status"]})
            if size == 32768 and r["status"] == 201:
                url_32768 = r["url"]

        assert states[0]["status"] == 201  # 16384 принято
        # наивный подсчёт отклонил бы 32767 (16384+32767 > B), правильная дельта — нет
        assert states[1]["status"] == 201  # замена на 32767 = B−1
        assert states[2]["status"] == 201  # замена на 32768 = B
        assert helpers.is_rejected(states[3]["status"])  # замена на 32769 = B+1

        # после отказа остаётся прежний объект 32768, счётчик = 1
        _, rows = helpers.list_rows()
        own = [r for r in rows if r.get("name") == name]
        assert len(own) == 1, f"ожидался 1 объект с именем {name}, в списке {len(own)}"
        assert own[0]["size"] == 32768, own[0]

        dl = stand.client.download(url_32768)
        assert dl["status"] == 200 and dl["bytes"] == 32768
        sub["replace_delta"] = {"states": states, "final_size": own[0]["size"]}
    else:
        # --- сумма при версиях ---
        s1, s2, s3 = 16000, 16000, 8000
        r1 = stand.client.upload(name, binary_payload(s1, seed=1))
        r2 = stand.client.upload(name, binary_payload(s2, seed=2))
        r3 = stand.client.upload(name, binary_payload(s3, seed=3))
        journal.extend([
            {"name": name, "source_bytes": s1, "status": r1["status"], "receipt": r1.get("receipt")},
            {"name": name, "source_bytes": s2, "status": r2["status"], "receipt": r2.get("receipt")},
            {"name": name, "source_bytes": s3, "status": r3["status"], "receipt": r3.get("receipt")},
        ])
        assert r1["status"] == 201 and r2["status"] == 201
        # s1+s2 = 32000 <= B; s1+s2+s3 = 40000 > B → отказ по сумме
        assert helpers.is_rejected(r3["status"])
        sub["versioned_sum"] = {
            "accepted_bytes": s1 + s2,
            "rejected_status": r3["status"],
            "limit": B,
        }

    # --- освобождение при удалении (вопрос владельцу, не эмулируется) ---
    if stand.policy["delete"]:
        sub["delete_frees"] = {
            "status": "incomplete",
            "reason": ("маршрут DELETE не подтверждён в CONTRACT.md и у fileqa.client.Client "
                       "нет метода delete — не изобретаем сигнатуру; нужен подтверждённый маршрут"),
        }
    else:
        sub["delete_frees"] = {"status": "not-applicable",
                               "reason": "policy.delete=false — удаление не подтверждено"}

    helpers.record(
        "C03",
        status="pass",
        collision=collision,
        logical_bytes_limit=B,
        sub=sub,
        journal=journal,
    )
