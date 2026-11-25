"""Подготовка фикстуры и манифеста для k6 и проверок квот.

CLI: python3 -m fileqa.prepare --profile profiles/live.json --run <id> --size 262 --out manifest.json

Загружает один бинарный файл с уникальным именем, записывает манифест
(fileqa-manifest v1) с объектом и печатает сводку (url, sha256, name).
Не повторяет POST автоматически.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from .client import Client
from .config import load_profile, origin_of, field_of, upload_path_of
from .digest import sha256
from .fixtures import binary_payload, unique_name
from .manifest import add_object, create, dump


def run_id_default() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-prep"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="путь к профилю")
    parser.add_argument("--run", default=None, help="run-id (по умолчанию UTC+суффикс)")
    parser.add_argument("--size", type=int, default=262, help="размер фикстуры, байт")
    parser.add_argument("--seed", type=int, default=0, help="seed бинарной фикстуры")
    parser.add_argument("--out", required=True, help="куда писать манифест JSON")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    origin = origin_of(profile)
    run_id = args.run or run_id_default()
    name = unique_name(run_id=run_id)
    data = binary_payload(args.size, seed=args.seed)

    with Client(origin, field=field_of(profile), upload_path=upload_path_of(profile)) as c:
        up = c.upload(name, data)
        if up["status"] != 201:
            print(json.dumps({"error": "upload rejected", "status": up["status"], "trace": c.trace},
                             ensure_ascii=False), file=sys.stderr)
            return 2
        saved_name = up.get("name") or name
        url = up.get("url")
        if not url:
            url = "/files/" + saved_name
        manifest = create(run_id, profile["name"], origin,
                          build=profile.get("build", "unknown"),
                          quota=profile.get("limits", {}), slo=profile.get("slo") or {})
        add_object(manifest, name, saved_name, url, len(data), sha256(data), run=run_id)
        dump(manifest, args.out)
        print(json.dumps({
            "run_id": run_id,
            "manifest": args.out,
            "name": saved_name,
            "url": url,
            "bytes": len(data),
            "sha256": sha256(data),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
