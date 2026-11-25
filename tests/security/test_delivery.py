"""SEC02 — выдача вложения: Content-Disposition, Content-Type и имя.

Загружаем собственный бинарный файл и читаем его по URL из квитанции. Проверяем
заголовки выдачи (attachment, отсутствие сниффинга) и имя согласно политике.
"""

from __future__ import annotations

import pytest

from fileqa.fixtures import binary_payload, unique_name


@pytest.mark.security
def test_attachment_headers_and_name(live, client, profile, recorder, run_id):
    name = unique_name(run_id=run_id, prefix="qa-sec", suffix=".bin")
    data = binary_payload(262)
    content_type = "application/octet-stream"

    up = client.upload(name, data, content_type=content_type)
    assert up.get("status") == 201, f"загрузка не принята: {up.get('status')}"
    url = up.get("url")
    assert url, "квитанция без url выдачи"

    dl = client.download(url)
    headers = dl.get("headers") or {}
    cd = headers.get("content-disposition", "")
    ct = headers.get("content-type", "")

    policy_names = (profile.get("policy") or {}).get("names", "unknown")

    recorder(
        "SEC02",
        status="observation",
        name_sent=name,
        name_saved=up.get("name"),
        url=url,
        download_status=dl.get("status"),
        content_disposition=cd,
        content_type_sent=content_type,
        content_type_delivered=ct,
        policy_names=policy_names,
        sha_matches=(dl.get("sha256") == up.get("source_sha256")),
    )

    # Выдача обязана быть 200 и возвращать ровно отправленные байты.
    assert dl.get("status") == 200
    assert dl.get("sha256") == up.get("source_sha256")

    # Content-Disposition обязан быть attachment — иначе браузер инлайнит контент.
    assert cd.lower().startswith("attachment"), f"ожидали attachment, получили {cd!r}"

    # Content-Type выдачи не «сниффится» в другой тип: равен заявленному клиентом.
    assert ct == content_type, f"Content-Type выдачи {ct!r} != заявленному {content_type!r}"

    # Имя в Content-Disposition соответствует политике (для ascii-имени).
    if policy_names in ("as-sent", "normalized"):
        assert name in cd, f"имя {name!r} не найдено в Content-Disposition {cd!r}"
