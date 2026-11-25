"""F05 — удаление. Только если профиль подтверждает маршрут удаления.

Для live-профиля `policy.delete == false`: тест пропускается с причиной
«нужен подтверждённый маршрут удаления». Остаточные записи всех принятых
загрузок запуска попадают в манифест через фикстуру `record_upload`.
"""

import pytest

from fileqa.config import policy_of
from fileqa.digest import sha256
from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.e2e
def test_f05_delete(client, run_id, profile, record, record_upload):
    record["case_id"] = "F05"

    if not policy_of(profile)["delete"]:
        record["reason"] = "нужен подтверждённый маршрут удаления"
        record["policy_delete"] = False
        pytest.skip("нужен подтверждённый маршрут удаления")

    # Удаление включено профилем. Маршрут в наблюдаемом контракте не подтверждён,
    # поэтому используется предполагаемый маршрут DELETE /files/{name}.
    import httpx
    from urllib.parse import quote

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")
    data = binary_payload(16, seed=9)

    up = client.upload(name, data)
    record_upload(up)
    assert 200 <= up["status"] < 300, f"F05: загрузка отклонена ({up['status']})"

    before = client.list_files()
    own_before = [r for r in (before["rows"] or []) if r.get("name") == name]

    with httpx.Client(
        base_url=client.origin, timeout=client.timeout, follow_redirects=False
    ) as hc:
        dele = hc.delete(client.upload_path + "/" + quote(name))

    after = client.list_files()
    own_after = [r for r in (after["rows"] or []) if r.get("name") == name]
    get_after = client.get(up["url"])

    record["name"] = name
    record["upload_status"] = up["status"]
    record["delete_status"] = dele.status_code
    record["own_before"] = own_before
    record["own_after"] = own_after
    record["get_after_status"] = get_after["status"]
    record["get_after_sha256"] = get_after["sha256"]

    assert own_before, "F05: запись не появилась до удаления"
    assert 200 <= dele.status_code < 300, f"F05: DELETE вернул {dele.status_code}"
    assert own_after == [], "F05: запись осталась в списке после удаления"
    assert get_after["status"] == 404, "F05: выдача не вернула 404 после удаления"
