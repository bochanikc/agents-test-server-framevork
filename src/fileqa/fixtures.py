"""Генерация тестовых данных: уникальные имена и бинарные фикстуры.

Имена несут случайный маркер запуска, чтобы запись теста отличалась от чужих
записей в общем списке. Бинарная фикстура содержит NUL и CRLF, чтобы проверка
побайтовой целостности не проходила случайно на текстовых нормализациях.
"""

from __future__ import annotations

import uuid


def run_marker(run_id: str | None = None) -> str:
    """Короткий уникальный маркер запуска (или новый)."""
    return (run_id or uuid.uuid4().hex)[:8]


def unique_name(run_id: str | None = None, prefix: str = "qa", suffix: str = ".bin") -> str:
    """Уникальное имя вида qa-<run>-<uuid><suffix>."""
    return f"{prefix}-{run_marker(run_id)}-{uuid.uuid4().hex}{suffix}"


def binary_payload(size: int, seed: int = 0) -> bytes:
    """Бинарные байты заданной длины с NUL и CRLF в начале.

    Генерируется детерминированно по seed (для повторяемости фикстур).
    """
    if size < 0:
        raise ValueError("size должен быть >= 0")
    if size == 0:
        return b""
    data = bytearray(size)
    for i in range(size):
        data[i] = (seed + i * 131 + i * i * 17) & 0xFF
    # Гарантируем наличие NUL и CRLF там, где это возможно.
    if size >= 8:
        data[0] = 0x00
        data[1] = 0x0D
        data[2] = 0x0A
        data[3] = 0x00
    return bytes(data)
