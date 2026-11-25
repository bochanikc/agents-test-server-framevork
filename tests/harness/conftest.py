"""Синтетический HTTP-дублёр файлового API для самопроверок инструментов.

Повторяет наблюдаемый контракт живого сервиса (квитанция с "uploaded", список
с name/path/size/content_type/fields), чтобы selftest не зависел от сети и не
создавал записей на реальном стенде.
"""

from __future__ import annotations

import json
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote, unquote

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def framework_root():
    return FRAMEWORK_ROOT


class SyntheticHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status, data, mime="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _storage_path(self, name):
        return f"/var/example-store/{uuid.uuid4().hex}_{name}"

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, b'{"status":"ok"}')
        if self.path == "/files":
            if self.server.truncated_list:
                # Наблюдаемый класс R2-040: 200 и Content-Length сходятся, но
                # JSON обрезан. HTTP-успех не должен считаться успехом разбора.
                return self._send(200, b'[{"name":"qa.bin","path":"/var/example-store/x_qa.bin","size":1')
            rows = [
                {
                    "name": name,
                    "path": entry["path"],
                    "size": len(entry["data"]),
                    "content_type": entry["content_type"],
                    "fields": [],
                }
                for name, entry in self.server.files.items()
            ]
            return self._send(200, json.dumps(rows).encode())
        name = unquote(self.path.removeprefix("/files/"))
        if name in self.server.files:
            entry = self.server.files[name]
            data = entry["data"]
            if self.server.corrupt and data:
                data = bytearray(data)
                data[0] ^= 0xFF
                data = bytes(data)
            return self._send(
                200,
                data,
                entry["content_type"],
                extra={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path != "/files":
            return self._send(404, b"{}")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        header = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
        parts = BytesParser(policy=policy.default).parsebytes(header + body).iter_parts()
        uploaded = []
        for part in parts:
            if part.get_param("name", header="Content-Disposition") == "file":
                name = part.get_filename()
                data = part.get_payload(decode=True) or b""
                content_type = part.get("Content-Type", "application/octet-stream")
                limit = self.server.single_file_bytes
                if limit is not None and len(data) > limit:
                    # Наблюдаемый контракт: предел применяется к части, а текст
                    # называет предел тела (R2-006). Формат — text/plain (R2-051).
                    self.send_response(413)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    message = f"Maximum request body size {limit} exceeded.".encode()
                    self.send_header("Content-Length", str(len(message)))
                    self.end_headers()
                    self.wfile.write(message)
                    return
                if self.server.collision == "reject" and name in self.server.files:
                    return self._send(409, b'{"error":"name exists"}')
                path = self.server.files[name]["path"] if name in self.server.files else self._storage_path(name)
                self.server.files[name] = {"data": data, "content_type": content_type, "path": path}
                uploaded.append({
                    "name": name,
                    "path": path,
                    "size": len(data),
                    "content_type": content_type,
                    "fields": [],
                    "url": "/files/" + quote(name),
                })
        if not uploaded:
            return self._send(400, b'{"error":"file required"}')
        return self._send(201, json.dumps({"uploaded": uploaded}).encode())


class _Server:
    def __init__(self, handler):
        self._http = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self._http.server_port
        # Атрибуты кладём на сам HTTPServer: обработчик видит их через self.server.
        self._http.files = {}
        self._http.corrupt = False
        self._http.collision = "replace"
        self._http.single_file_bytes = 1048576
        self._http.truncated_list = False
        self._thread = Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()

    @property
    def files(self):
        return self._http.files

    @property
    def corrupt(self):
        return self._http.corrupt

    @corrupt.setter
    def corrupt(self, value):
        self._http.corrupt = value

    @property
    def collision(self):
        return self._http.collision

    @collision.setter
    def collision(self, value):
        self._http.collision = value

    @property
    def single_file_bytes(self):
        return self._http.single_file_bytes

    @single_file_bytes.setter
    def single_file_bytes(self, value):
        self._http.single_file_bytes = value

    @property
    def truncated_list(self):
        return self._http.truncated_list

    @truncated_list.setter
    def truncated_list(self, value):
        self._http.truncated_list = value

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self._http.shutdown()
        self._http.server_close()
        self._thread.join()


@pytest.fixture(scope="session")
def synthetic_server():
    server = _Server(SyntheticHandler)
    yield server
    server.close()
