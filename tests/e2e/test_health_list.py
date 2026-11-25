"""H01, L01 — health и базовый список с появлением собственной записи."""

import pytest

from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.e2e
def test_h01_health(client, record):
    record["case_id"] = "H01"
    res = client.health()
    record["status"] = res["status"]
    record["json"] = res["json"]

    assert res["status"] == 200, f"H01: GET /health вернул {res['status']}"
    assert isinstance(res["json"], dict), "H01: тело /health — не объект JSON"
    assert res["json"].get("status") == "ok", "H01: нет status=ok"


@pytest.mark.e2e
def test_l01_list(client, run_id, record, record_upload):
    record["case_id"] = "L01"

    base = client.list_files()
    record["base_status"] = base["status"]
    assert base["status"] == 200, f"L01: GET /files вернул {base['status']}"
    assert isinstance(base["json"], list), "L01: /files вернул не JSON-массив"

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")
    data = binary_payload(32, seed=3)
    up = client.upload(name, data)
    record_upload(up)

    lst = client.list_files()
    own = [r for r in (lst["rows"] or []) if r.get("name") == name]

    record["name"] = name
    record["upload_status"] = up["status"]
    record["list_status"] = lst["status"]
    record["own"] = own

    assert 200 <= up["status"] < 300, f"L01: загрузка отклонена ({up['status']})"
    assert own, "L01: своя запись не появилась в списке"
    assert own[0].get("size") == len(data), (
        f"L01: size в списке {own[0].get('size')} != {len(data)}"
    )
