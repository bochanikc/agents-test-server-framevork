"""Проверяет данные одного прогона и собирает автономные HTML и Markdown."""
import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import quote

LABELS = {"pass": "Исправно", "fail": "Дефект", "observation": "Наблюдение"}
FIELDS = {"steps": "Шаги", "expected": "Ожидание и его основание", "actual": "Факт",
          "impact": "Влияние", "severity": "Серьёзность", "acceptance": "Критерий исправления",
          "diagnostics": "Что уточнить разработчику"}
SECTIONS = {"questions": "Вопросы владельцу", "gaps": "Что осталось проверить",
            "attribution": "Кто и что сделал"}


def require_text(obj, keys):
    for key in keys:
        if not isinstance(obj.get(key), str) or not obj[key].strip():
            raise ValueError(f"Требуется текстовое поле {key}")


def validate(run, data):
    require_text(data, ["title", "service", "target", "period", "environment", "decision", "reason", "next"])
    if data["decision"] not in ("HOLD", "GO", "NO-GO"):
        raise ValueError("Неизвестное решение")
    for key in SECTIONS:
        if not isinstance(data[key], list) or not all(isinstance(x, str) and x.strip() for x in data[key]):
            raise ValueError(f"Ожидается список строк {key}")
    seen = set()
    if not isinstance(data["cases"], list):
        raise ValueError("cases должен быть массивом")
    for case in data["cases"]:
        require_text(case, ["id", "title", "status", "steps", "expected", "actual", "repro"])
        key = case["id"]
        if key in seen or not re.fullmatch(r"[A-Z][A-Z0-9-]*", key):
            raise ValueError(f"Некорректный или повторный ID {key}")
        seen.add(key)
        if case["status"] not in LABELS or "\n" in case["repro"]:
            raise ValueError(f"{key}: статус или команда воспроизведения")
        if case["status"] == "fail":
            require_text(case, ["impact", "severity", "acceptance"])
            if case["severity"] not in ("Critical", "High", "Medium", "Low"):
                raise ValueError(f"{key}: неизвестная серьёзность")
        if not isinstance(case["evidence"], list) or not case["evidence"]:
            raise ValueError(f"{key}: нужны файлы доказательств")
        for item in case["evidence"]:
            path = (run / item).resolve()
            if not path.is_relative_to(run) or not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"{key}: нет локального доказательства {item}")
    passed = {c["id"] for c in data["cases"] if c["status"] == "pass"}
    required = data.get("required") or ["H01", "L01", "F01"]
    if not isinstance(required, list) or not all(isinstance(x, str) and x.strip() for x in required):
        raise ValueError("required должен быть непустым списком ID")
    if data["decision"] == "GO" and not set(required) <= passed:
        missing = sorted(set(required) - passed)
        raise ValueError("GO требует подтверждения обязательных кейсов: " + ", ".join(missing))
    if data["decision"] == "NO-GO" and not any(c["status"] == "fail" for c in data["cases"]):
        raise ValueError("NO-GO требует подтверждённого дефекта")


def markdown(d):
    parts = [f"# {d['title']}", d["service"], f"**{d['decision']}** — {d['reason']}",
             f"**Следующее действие.** {d['next']}",
             f"**Стенд** `{d['target']}`  \n**Время** {d['period']}  \n**Клиент** {d['environment']}"]
    if d.get("parent_run"):
        parts.append(f"Исходный прогон — {d['parent_run']}")
    for c in d["cases"]:
        parts.append(f"## {c['id']} · {c['title']} · {c['status']}")
        for k, label in FIELDS.items():
            if c.get(k):
                parts.append(f"**{label}.** {c[k]}")
        parts += ["Команда из корня проекта", "```sh\n" + c["repro"] + "\n```",
                  "Доказательства — " + ", ".join(f"[{p}]({quote(p)})" for p in c["evidence"])]
    for k, title in SECTIONS.items():
        parts.append(f"## {title}")
        parts.append("\n".join("- " + x for x in d[k]) or "Нет записей для этого прогона.")
    return "\n\n".join(parts) + "\n"


STYLE = """
*{box-sizing:border-box}body{margin:0;background:#edf2f1;color:#183330;font:16px/1.55 Inter,system-ui,sans-serif}
main{max-width:960px;margin:28px auto;background:white;padding:clamp(20px,5vw,60px);border-top:7px solid #155e55}
h1,h2,h3,p{margin:0 0 .65em}h1{font-size:clamp(30px,5vw,50px);line-height:1.08;letter-spacing:-.035em}
h2{font-size:23px;margin-top:1.5em}h3{font-size:18px}header small,.meta{color:#496460}
.gate{background:#eff6f3;border-left:5px solid #155e55;padding:17px 22px;margin:22px 0}
.gate.HOLD{background:#fff6df;border-color:#ad731a}.gate.NO-GO{background:#fff0ed;border-color:#a53828}
.counts{display:flex;gap:22px;flex-wrap:wrap}.counts span{border-bottom:1px solid #b4c7c2;padding:8px 0}
article{padding:14px 0;border-bottom:1px solid #dce7e4}summary,a{color:#125e53}
details{margin-top:8px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf4f3;padding:10px}
.id{color:#58726b;font:13px monospace}li{margin:5px 0}p,li,a{overflow-wrap:anywhere}
@media print{body,main{margin:0;background:white}main{padding:8mm}article,.gate{break-inside:avoid}}
"""


def html(d):
    e = escape
    count = Counter(c["status"] for c in d["cases"])
    out = ['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>{e(d["title"])}</title><style>{STYLE}</style><main><header><small>QA / Файловый API</small>',
           f'<h1>{e(d["title"])}</h1><p>{e(d["service"])}</p></header>',
           f'<section class="gate {e(d["decision"])}"><h2 style="margin:0">{e(d["decision"])}</h2><p>{e(d["reason"])}</p><strong>Следующее действие</strong><p>{e(d["next"])}</p></section>',
           f'<p class="meta">{e(d["target"])} · {e(d["period"])}<br>{e(d["environment"])}</p>',
           '<div class="counts">' + "".join(f'<span>{label} · <b>{count[k]}</b></span>' for k, label in LABELS.items()) + '</div>']
    for k, title in [("fail","Подтверждённые дефекты"), ("pass","Что работает"), ("observation","Наблюдения")]:
        cards = [c for c in d["cases"] if c["status"] == k]
        if not cards:
            continue
        out.append(f"<h2>{title}</h2>")
        for c in cards:
            out.append(f'<article><span class="id">{e(c["id"])} {e(c.get("severity",""))}</span><h3>{e(c["title"])}</h3><p>{e(c["actual"])}</p>')
            if c.get("impact"):
                out.append("<p>" + e(c["impact"]) + "</p>")
            out.append('<details><summary>Как проверяли</summary>')
            for f in ("steps","expected","acceptance","diagnostics"):
                if c.get(f):
                    out.append(f'<p><b>{FIELDS[f]}.</b> {e(c[f])}</p>')
            out.append(f'<pre>{e(c["repro"])}</pre>' + " · ".join(f'<a href="{quote(p)}">{e(p)}</a>' for p in c["evidence"]) + '</details></article>')
    for k, title in SECTIONS.items():
        if d[k]:
            out += [f'<h2>{title}</h2><ul>', *[f'<li>{e(x)}</li>' for x in d[k]], '</ul>']
    out.append('<footer><a href="developer.md">Технический отчёт с командами воспроизведения</a></footer></main></html>')
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    run = parser.parse_args().run.resolve()
    try:
        d = json.loads((run / "results.json").read_text(encoding="utf-8"))
        validate(run, d)
        md, page = markdown(d), html(d)
        (run / "developer.md").write_text(md, encoding="utf-8")
        (run / "report.html").write_text(page, encoding="utf-8")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(1, f"Отчёты не собраны: {exc}\n")


if __name__ == "__main__":
    main()
