"""Хеширование и размеры. Единицы — байты; SHA-256 — в нижнем регистре hex."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256(data: bytes) -> str:
    """SHA-256 в виде 64 символов нижнего регистра hex."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """SHA-256 файла без загрузки целиком в память."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_hex_sha256(value: str) -> bool:
    """Строка — ровно 64 символа нижнего регистра hex."""
    if not isinstance(value, str):
        return False
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
