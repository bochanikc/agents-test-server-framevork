"""HTTP-клиент чёрного ящика. Один вызов HTTPX на шаг, явные таймауты.

Контракт для остальных ролей:
  * `Client.health()`        -> dict  {"status", "json", ...}
  * `Client.list_files()`    -> dict  {"status", "json", "rows", "complete", ...}
  * `Client.upload(name, data)` -> dict {"status", "receipt", "url", "name", "size", ...}
  * `Client.upload_many([(name, data), ...])` -> тот же словарь плюс `uploaded`
    (все квитанции), `items` (сопоставление часть ↔ квитанция) и `request_bytes`
  * `Client.download(url)`   -> dict  {"status", "bytes", "sha256", "headers", ...}
  * `Client.get(path)`       -> dict  {"status", "bytes", "headers", ...}

Все методы пишут запись в `client.trace` (список словарей), чтобы запись
доказательств была единой. URL выдачи проверяется на принадлежность origin.
HTTP-успех не равен успеху разбора: `list_files()` отдаёт `complete`, а отказ
(status >= 400) — поле `error` с текстом независимо от формата тела (JSON или
text/plain).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

from .digest import sha256

_SCHEME_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(?::\d+)?$")

# Заголовки, которые сохраняем в доказательства (не чувствительные).
KEEP_HEADERS = (
    "content-type",
    "content-length",
    "content-disposition",
    "date",
    "allow",
    "server",
    "x-request-id",
)


def validate_origin(origin: str) -> str:
    """Нормализует origin: только схема + хост + необязательный порт."""
    origin = (origin or "").strip().rstrip("/")
    if not _SCHEME_RE.fullmatch(origin):
        raise ValueError(
            "origin должен содержать только схему, хост и необязательный порт: "
            f"{origin!r}"
        )
    return origin


def _clean_headers(headers: httpx.Headers) -> dict:
    out: dict = {}
    for key, value in headers.items():
        if key.lower() in KEEP_HEADERS:
            out[key.lower()] = value
    return out


class Client:
    """HTTPX Client на сессию исполнителя. Один вызов на шаг."""

    def __init__(
        self,
        origin: str,
        timeout: float = 15.0,
        connect_timeout: float = 8.0,
        field: str = "file",
        upload_path: str = "/files",
    ) -> None:
        self.origin = validate_origin(origin)
        self.field = field
        self.upload_path = upload_path
        self.timeout = timeout
        self.trace: list[dict] = []
        self._c = httpx.Client(
            base_url=self.origin,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            follow_redirects=False,
        )

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _resolve(self, url: str) -> str:
        """Допускает только относительный путь или тот же origin."""
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            # Абсолютный URL обязан указывать на тот же origin.
            base = urlsplit(self.origin)
            if parts.scheme != base.scheme or parts.netloc != base.netloc:
                raise ValueError(f"URL вне origin: {url!r}")
            return url
        if not url.startswith("/"):
            raise ValueError(f"Нужен относительный путь от корня: {url!r}")
        return url

    def _record(self, method: str, path: str, resp: httpx.Response, body: bytes) -> dict:
        record = {
            "method": method,
            "path": path,
            "status": resp.status_code,
            "elapsed_s": resp.elapsed.total_seconds() if resp.elapsed else None,
            "bytes": len(body),
            "sha256": sha256(body),
            "headers": _clean_headers(resp.headers),
        }
        if resp.status_code >= 400:
            # Диагностика не зависит от формата: 400/404 — JSON, 413 — text/plain.
            record["error"] = error_message(body)
        self.trace.append(record)
        return record

    def health(self) -> dict:
        resp = self._c.get("/health")
        body = resp.read()
        record = self._record("GET", "/health", resp, body)
        record["json"] = _try_json(body)
        return record

    def list_files(self) -> dict:
        resp = self._c.get("/files")
        body = resp.read()
        record = self._record("GET", "/files", resp, body)
        record["json"] = _try_json(body)
        record["rows"] = record["json"] if isinstance(record["json"], list) else None
        # 200 не означает успех: обрезанный или не-массив JSON даёт rows=None.
        record["json_ok"] = record["json"] is not None
        record["complete"] = isinstance(record["json"], list)
        return record

    def upload(
        self,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """Одна файловая часть. Совместимая обёртка над `upload_many`."""
        return self.upload_many([(name, data)], content_type=content_type)

    def upload_many(
        self,
        items: list[tuple[str, bytes]] | list[dict],
        content_type: str = "application/octet-stream",
    ) -> dict:
        """Пакет файловых частей одним POST. Квитанции возвращаются все.

        `items` — список пар (имя, байты) либо словарей с ключами
        `name`/`data`/`content_type`. Тело запроса собирается заранее, поэтому
        `request_bytes` — фактическая длина multipart-конверта, а не сумма
        частей. Поля первого объекта сохранены для совместимости с `upload()`.
        """
        sent = _source_items(items, default_content_type=content_type)
        if not sent:
            raise ValueError("upload_many: нужен хотя бы один файл")
        files = [
            (self.field, (item["name_sent"], item["data"], item["content_type"]))
            for item in sent
        ]
        request = self._c.build_request("POST", self.upload_path, files=files)
        request_bytes = len(request.read())
        resp = self._c.send(request)
        body = resp.read()
        record = self._record("POST", self.upload_path, resp, body)
        record["request_bytes"] = request_bytes
        record["source_items"] = [
            {
                "name_sent": item["name_sent"],
                "source_bytes": len(item["data"]),
                "source_sha256": sha256(item["data"]),
                "content_type": item["content_type"],
            }
            for item in sent
        ]
        receipt = _try_json(body)
        record["receipt"] = receipt
        uploaded = _uploaded_items(receipt)
        record["uploaded"] = uploaded
        record["receipts_count"] = len(uploaded)
        record["items"], record["items_matched_by"] = _match_items(
            record["source_items"], uploaded
        )
        # Отправленная часть фиксируется всегда, даже при отказе без квитанции.
        record["name_sent"] = sent[0]["name_sent"]
        record["source_bytes"] = len(sent[0]["data"])
        record["source_sha256"] = sha256(sent[0]["data"])
        # Совместимость с одиночной загрузкой: поля первой квитанции.
        first = uploaded[0] if uploaded else None
        if first is not None:
            record["name"] = first.get("name")
            record["url"] = first.get("url")
            record["path"] = first.get("path")
            record["size"] = first.get("size")
            record["content_type"] = first.get("content_type")
        return record

    def download(self, url: str) -> dict:
        path = self._resolve(url)
        resp = self._c.get(path)
        body = resp.read()
        record = self._record("GET", path, resp, body)
        record["sha256"] = sha256(body)
        return record

    def get(self, path: str) -> dict:
        path = self._resolve(path)
        resp = self._c.get(path)
        body = resp.read()
        record = self._record("GET", path, resp, body)
        record["sha256"] = sha256(body)
        return record


def _try_json(body: bytes):
    import json

    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        return None


def error_message(body: bytes) -> str | None:
    """Текст отказа для диагностики независимо от формата тела.

    JSON с полем `error` (400/404 наблюдаемого сервиса) и текстовое тело
    (413 `text/plain`) дают строку; пустое тело — None. Разбор только через
    `json.loads` на 413 вернул бы None и потерял сообщение клиенту.
    """
    if not body:
        return None
    parsed = _try_json(body)
    if isinstance(parsed, dict):
        for key in ("error", "detail", "message"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    text = body.decode("utf-8", "replace").strip()
    return text or None


def _uploaded_items(receipt) -> list:
    """Все элементы квитанции загрузки независимо от формы ответа."""
    if isinstance(receipt, dict) and isinstance(receipt.get("uploaded"), list):
        items = receipt["uploaded"]
    elif isinstance(receipt, list):
        items = receipt
    else:
        return []
    return [item for item in items if isinstance(item, dict)]


def _source_items(items: list, default_content_type: str) -> list:
    """Нормализует вход `upload_many` к списку с именем, байтами и типом."""
    out = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name")
            data = item.get("data")
            mime = item.get("content_type") or default_content_type
        else:
            name, data = item
            mime = default_content_type
        if not isinstance(name, str) or not name:
            raise ValueError("upload_many: у части нет имени")
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("upload_many: данные части должны быть bytes")
        out.append({"name_sent": name, "data": bytes(data), "content_type": mime})
    return out


def _match_items(source_items: list, uploaded: list) -> tuple[list, str]:
    """Сопоставляет отправленные части с квитанциями.

    Приоритет — совпадение имени; иначе порядок (наблюдение p03/p04: квитанции
    идут в порядке частей). Способ сопоставления пишется в запись.
    """
    by_name = {
        item.get("name"): item
        for item in uploaded
        if isinstance(item.get("name"), str)
    }
    if uploaded and len(by_name) == len(uploaded) and all(
        item["name_sent"] in by_name for item in source_items
    ):
        matched, mode = [
            {"name_sent": item["name_sent"],
             "source_bytes": item["source_bytes"],
             "source_sha256": item["source_sha256"],
             "receipt": by_name[item["name_sent"]]}
            for item in source_items
        ], "name"
    else:
        matched, mode = [
            {"name_sent": item["name_sent"],
             "source_bytes": item["source_bytes"],
             "source_sha256": item["source_sha256"],
             "receipt": uploaded[i] if i < len(uploaded) else None}
            for i, item in enumerate(source_items)
        ], "index"
    return matched, mode
