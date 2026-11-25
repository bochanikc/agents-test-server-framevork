"""SEC01 — транспорт: фактическая схема и учётные данные в штатном запросе.

Наблюдение, а не атака: обычный запрос без учётных данных к объявленной точке
входа. Фиксируем фактическую схему (HTTP/HTTPS) и отсутствие требования
авторизации (нет 401-challenge). Если профиль заявляет иное — это несоответствие.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest


@pytest.mark.security
def test_transport_scheme_and_credentials(live, origin, profile, recorder):
    scheme = urlsplit(origin).scheme
    sec = profile.get("security") or {}
    expected_transport = sec.get("transport", "unknown")
    expected_auth = sec.get("auth", "unknown")

    # Учётные данные в штатном запросе отсутствуют (клиент их не отправляет),
    # а точка входа не ответила 401 с challenge.
    challenge = "www-authenticate" in (live.get("headers") or {})
    auth_observed = "none" if not challenge else "challenged"

    recorder(
        "SEC01",
        status="observation",
        origin=origin,
        scheme=scheme,
        expected_transport=expected_transport,
        auth_observed=auth_observed,
        expected_auth=expected_auth,
        health_status=live.get("status"),
    )

    # Факт достижимости точки входа обычным запросом.
    assert live.get("status") is not None

    # Только когда профиль требует конкретную схему — сверяем фактическую.
    if expected_transport == "https":
        assert scheme == "https", f"профиль требует https, наблюдаем {scheme}"
    elif expected_transport == "http":
        assert scheme == "http", f"профиль заявляет http, наблюдаем {scheme}"

    # Только когда профиль требует авторизацию — её отсутствие есть нарушение.
    if expected_auth == "required":
        assert auth_observed == "challenged", (
            "профиль требует авторизацию, но точка входа её не потребовала"
        )
