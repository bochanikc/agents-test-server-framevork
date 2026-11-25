"""Самопроверка HTTP-клиента на синтетическом дублёре.

Проверяет происхождение URL, целостность байтов и выявление изменённого
содержимого той же длины — базовые свойства, на которых стоят E2E и k6.
"""

import pytest

from fileqa.client import Client, error_message, validate_origin
from fileqa.digest import sha256


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("http://example.com", "http://example.com"),
        ("https://example.com:8443", "https://example.com:8443"),
        ("http://files.example.com", "http://files.example.com"),
        ("http://example.com/", "http://example.com"),
    ],
)
def test_validate_origin_ok(origin, expected):
    assert validate_origin(origin) == expected


@pytest.mark.parametrize(
    "origin",
    ["example.com", "ftp://example.com", "http://example.com/path", "", "http://"],
)
def test_validate_origin_bad(origin):
    with pytest.raises(ValueError):
        validate_origin(origin)


def test_upload_list_download_roundtrip(synthetic_server):
    data = b"\x00\x0d\x0ahello\r\nworld"
    with Client(synthetic_server.origin) as c:
        up = c.upload("qa.bin", data)
        assert up["status"] == 201
        assert up["name"] == "qa.bin"
        assert up["url"] == "/files/qa.bin"
        assert up["size"] == len(data)

        lst = c.list_files()
        assert lst["status"] == 200
        rows = {r["name"]: r for r in lst["rows"]}
        assert rows["qa.bin"]["size"] == len(data)
        assert rows["qa.bin"]["path"].startswith("/var/example-store/")

        dl = c.download(up["url"])
        assert dl["status"] == 200
        assert dl["bytes"] == len(data)
        assert dl["sha256"] == sha256(data)


def test_corrupt_same_length_detected(synthetic_server):
    data = b"A" * 64
    with Client(synthetic_server.origin) as c:
        up = c.upload("q.bin", data)
        synthetic_server.corrupt = True
        try:
            dl = c.download(up["url"])
        finally:
            synthetic_server.corrupt = False
        # длина та же, байты другие — оракул обязан это заметить
        assert dl["bytes"] == len(data)
        assert dl["sha256"] != sha256(data)


def test_cross_origin_download_rejected(synthetic_server):
    with Client(synthetic_server.origin) as c:
        with pytest.raises(ValueError):
            c.download("http://evil.example.com/steal")


def test_missing_file_distinct(synthetic_server):
    with Client(synthetic_server.origin) as c:
        dl = c.get("/files/does-not-exist")
        assert dl["status"] == 404


def test_error_message_reads_json_and_plain_text():
    # 400/404 наблюдаемого сервиса — JSON с полем error.
    assert error_message(b'{"error":"file required"}') == "file required"
    assert error_message('{"error":"не найден файл"}'.encode()) == "не найден файл"
    # 413 — text/plain: обработчик, ждущий только JSON, вернул бы None.
    text = b"Maximum request body size 1048576 exceeded."
    assert error_message(text) == text.decode()
    assert error_message(b"") is None


def test_plain_text_413_kept_in_diagnostics(synthetic_server):
    limit = synthetic_server.single_file_bytes
    data = b"x" * (limit + 1)
    try:
        with Client(synthetic_server.origin) as c:
            up = c.upload("qa-413.bin", data)
    finally:
        synthetic_server.single_file_bytes = 1048576
    assert up["status"] == 413
    assert up["receipt"] is None
    assert up["headers"]["content-type"].startswith("text/plain")
    assert up["error"] == f"Maximum request body size {limit} exceeded."
    # Ключи отправленной части остаются доступны для карточки доказательств.
    assert up["source_bytes"] == limit + 1


def test_json_404_kept_in_diagnostics(synthetic_server):
    with Client(synthetic_server.origin) as c:
        dl = c.get("/files/does-not-exist")
    assert dl["status"] == 404
    assert dl["error"] == "not found"


def test_truncated_list_is_not_success(synthetic_server):
    synthetic_server.truncated_list = True
    try:
        with Client(synthetic_server.origin) as c:
            lst = c.list_files()
    finally:
        synthetic_server.truncated_list = False
    assert lst["status"] == 200
    assert lst["json"] is None
    assert lst["rows"] is None
    assert lst["json_ok"] is False
    assert lst["complete"] is False


def test_batch_upload_returns_all_receipts(synthetic_server):
    items = [("qa-empty.bin", b""), ("qa-one.bin", b"\x00"), ("qa-pair.bin", b"abc")]
    with Client(synthetic_server.origin) as c:
        up = c.upload_many(items)
        assert up["status"] == 201
        assert up["receipts_count"] == len(items)
        assert up["items_matched_by"] == "name"
        assert len(up["uploaded"]) == len(items)
        for source, item in zip(items, up["items"]):
            receipt = item["receipt"]
            assert receipt["name"] == source[0]
            assert receipt["size"] == len(source[1])
            assert item["source_bytes"] == len(source[1])
            dl = c.download(receipt["url"])
            assert dl["status"] == 200
            assert dl["bytes"] == len(source[1])
            assert dl["sha256"] == sha256(source[1])
        # Тело запроса длиннее суммы частей: конверт multipart учтён отдельно.
        assert up["request_bytes"] > sum(len(data) for _, data in items)
