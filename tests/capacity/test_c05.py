"""C05 — фактическая ёмкость: прогноз занятого места по входным параметрам.

Без серверных данных — только логический объём. Входные параметры оператора —
в profile.capacity. Расчёт: загрузки/сутки × средний размер × срок хранения;
версии, репликацию и бэкапы считаем отдельно (если заданы). Нижняя граница —
из предоставленного манифеста наблюдения (если есть). Сеть не используется.
"""

import pytest

from fileqa.manifest import load as load_manifest


@pytest.mark.capacity
def test_c05_actual_capacity_forecast(stand, helpers):
    cap = stand.profile.get("capacity") or {}
    uploads_per_day = cap.get("uploads_per_day")
    avg = cap.get("avg_size_bytes")
    retention = cap.get("retention_days")
    replication = cap.get("replication")          # None = неизвестно
    backups = cap.get("backup_copies")            # None = неизвестно
    version_overhead = cap.get("version_overhead")  # None = неизвестно (0.0 = нет)

    inputs = {
        "uploads_per_day": uploads_per_day,
        "avg_size_bytes": avg,
        "retention_days": retention,
        "replication": replication,
        "backup_copies": backups,
        "version_overhead": version_overhead,
        "scope": stand.limits.get("scope"),
    }

    if uploads_per_day is None or avg is None or retention is None:
        helpers.record(
            "C05",
            status="incomplete",
            reason=("нет входных параметров оператора (uploads_per_day/avg_size_bytes/"
                    "retention_days) в profile.capacity — прогноз невозможен"),
            inputs=inputs,
        )
        return

    logical = uploads_per_day * avg * retention
    with_version = logical * (1 + (version_overhead if version_overhead is not None else 0.0))
    storage = None
    if replication is not None and backups is not None:
        storage = with_version * replication * (1 + backups)

    lower_bound = None
    obs = cap.get("observed_manifest")
    if obs:
        m = load_manifest(obs)
        lower_bound = {
            "objects": len(m["objects"]),
            "bytes": sum(o["bytes"] for o in m["objects"]),
        }

    helpers.record(
        "C05",
        status="pass",
        inputs=inputs,
        logical_forecast_bytes=logical,
        storage_forecast_bytes=storage,
        observed_lower_bound=lower_bound,
    )
