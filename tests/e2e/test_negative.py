"""N01, N02 — отрицательные сценарии.

N01: форма без файловой части (multipart с текстовым полем, без части `file`)
должна дать понятный отказ 4xx, и своя новая запись НЕ появляется. Это
единственный сценарий, которому нужен «сырой» POST: `Client.upload` всегда
прикладывает файловую часть, поэтому тело формы без файла отправляется через
httpx напрямую.

N02: GET /files/{отсутствующее своё имя} → 404, отличим от успешной выдачи.
"""

import httpx
import pytest

from fileqa.fixtures import unique_name


@pytest.mark.e2e
def test_n01_form_without_file(client, run_id, record):
    record["case_id"] = "N01"

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")

    # multipart с текстовым полем, без части "file".
    with httpx.Client(
        base_url=client.origin, timeout=client.timeout, follow_redirects=False
    ) as hc:
        resp = hc.post(client.upload_path, files={"note": (None, name)})

    status = resp.status_code
    lst = client.list_files()
    own = [r for r in (lst["rows"] or []) if r.get("name") == name]

    record["name"] = name
    record["post_status"] = status
    record["matching_entries"] = len(own)

    assert 400 <= status < 500, f"N01: ожидался понятный отказ 4xx, получено {status}"
    assert own == [], f"N01: своя запись не должна появляться, найдено {len(own)}"


@pytest.mark.e2e
def test_n02_missing_file(client, run_id, record):
    record["case_id"] = "N02"

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")  # никогда не загружалось
    res = client.get(f"/files/{name}")

    record["name"] = name
    record["status"] = res["status"]
    record["bytes"] = res["bytes"]
    record["content_type"] = res["headers"].get("content-type")

    assert res["status"] == 404, f"N02: ожидался 404, получено {res['status']}"
    assert res["status"] != 200, "N02: отсутствующий объект не отличим от успешной выдачи"
