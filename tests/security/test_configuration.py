"""SEC06 — конфигурация: лимиты, роли, срок хранения сверяются с профилем.

Сверяем настройки по конфигурации из профиля. Заявленные значения проверяются на
корректность; отсутствующие значения — не провал, а вопрос владельцу (фиксируется
в evidence и в docs/security.md).
"""

from __future__ import annotations

import pytest

from fileqa.config import limits_of, policy_of


@pytest.mark.security
def test_configuration_declared_or_question(live, profile, recorder):
    limits = limits_of(profile)
    policy = policy_of(profile)
    sec = profile.get("security") or {}
    sources = profile.get("sources") or {}

    declared: dict = {}
    questions: list = []

    # Лимиты: сверяем по конфигурации из профиля.
    for key in ("single_file_bytes", "object_count", "logical_bytes"):
        value = limits.get(key)
        source = sources.get(f"limits.{key}", sources.get("limits", "—"))
        if value is None:
            questions.append(f"limits.{key}: не задано (источник: {source}) — владелец сервиса")
        else:
            assert isinstance(value, int) and value >= 0, f"limits.{key}={value!r} не число"
            declared[f"limits.{key}"] = {"value": value, "source": source}

    # Роли / модель доступа.
    roles = sec.get("roles")
    if roles is None:
        questions.append("security.roles: кто может перечислять/скачивать/загружать — владелец продукта")
    else:
        declared["security.roles"] = roles

    # Срок хранения.
    retention = sec.get("retention")
    if retention is None:
        questions.append("security.retention: срок хранения не задан — владелец сервиса")
    else:
        declared["security.retention"] = retention

    recorder(
        "SEC06",
        status="observation",
        declared=declared,
        questions=questions,
        limits_scope=limits.get("scope"),
        policy=policy,
        sources=sources,
    )

    # Отсутствие конфигурации — не провал, а открытый вопрос владельцу.
    # (вопросы зафиксированы в evidence/SEC06.json и docs/security.md)
