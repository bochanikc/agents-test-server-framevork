"""F01, F02, F03 — загрузка бинарных данных и целостность байтов."""

import uuid

import pytest

from fileqa.digest import sha256
from fileqa.fixtures import binary_payload, run_marker, unique_name


@pytest.mark.e2e
def test_f01_roundtrip(client, run_id, record, record_upload):
    record["case_id"] = "F01"

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")
    data = binary_payload(256, seed=4)
    assert b"\x00" in data and b"\r\n" in data  # фикстура содержит NUL и CRLF
    source_sha = sha256(data)

    up = client.upload(name, data)
    record_upload(up)
    lst = client.list_files()
    own = [r for r in (lst["rows"] or []) if r.get("name") == name]
    dl = client.download(up["url"])

    record["name"] = name
    record["upload_status"] = up["status"]
    record["url"] = up["url"]
    record["own"] = own
    record["source_sha256"] = source_sha
    record["download_status"] = dl["status"]
    record["download_bytes"] = dl["bytes"]
    record["download_sha256"] = dl["sha256"]

    assert 200 <= up["status"] < 300, f"F01: загрузка отклонена ({up['status']})"
    assert own and own[0].get("size") == len(data), "F01: запись списка не сходится"
    assert dl["status"] == 200, f"F01: скачивание вернуло {dl['status']}"
    assert dl["bytes"] == len(data), "F01: длина скачанного не совпадает"
    assert dl["sha256"] == source_sha, "F01: SHA-256 не совпадает (побайтовое расхождение)"


@pytest.mark.e2e
def test_f02_empty(client, run_id, record, record_upload):
    record["case_id"] = "F02"

    name = unique_name(run_id=run_id, prefix="qa", suffix=".bin")
    data = b""

    up = client.upload(name, data)
    record_upload(up)
    lst = client.list_files()
    own = [r for r in (lst["rows"] or []) if r.get("name") == name]

    record["name"] = name
    record["upload_status"] = up["status"]
    record["source_sha256"] = sha256(b"")
    record["own"] = own

    assert 200 <= up["status"] < 300, f"F02: пустой файл отклонён ({up['status']})"
    assert up["source_sha256"] == sha256(b""), "F02: SHA пустого тела не сходится"
    assert own and own[0].get("size") == 0, "F02: запись пустого файла не появилась"


@pytest.mark.e2e
def test_f03_cyrillic_space(client, run_id, record, record_upload):
    record["case_id"] = "F03"

    name = f"qa-{run_marker(run_id)}-{uuid.uuid4().hex} файл.bin"  # кириллица и пробел
    data = binary_payload(128, seed=5)
    source_sha = sha256(data)

    up = client.upload(name, data)
    record_upload(up)
    saved = up.get("name")
    lst = client.list_files()
    candidates = [
        r for r in (lst["rows"] or []) if r.get("name") in (saved, name)
    ]
    dl = client.download(up["url"])

    record["name_sent"] = name
    record["name_receipt"] = saved
    record["candidates"] = candidates
    record["download_status"] = dl["status"]
    record["download_bytes"] = dl["bytes"]
    record["download_sha256"] = dl["sha256"]
    record["content_disposition"] = dl["headers"].get("content-disposition")
    record["source_sha256"] = source_sha

    # Содержимое обязано сохраниться — потеря байтов есть дефект независимо от
    # нормализации имени.
    assert dl["status"] == 200, f"F03: скачивание вернуло {dl['status']}"
    assert dl["bytes"] == len(data), "F03: длина скачанного не совпадает"
    assert dl["sha256"] == source_sha, "F03: SHA не совпадает (потеря байтов)"
    # Нормализация имени — наблюдение; своя запись по сохранённому/отправленному
    # имени должна быть найдена.
    assert candidates, "F03: своя запись не найдена в списке"
