# fileqa — переносимые автотесты файлового API

**Результат тестового задания от 25 ноября 2026 г. — NO-GO.** [Итог, проблемы, вопросы и следующие шаги](reports/release.md) · [Технический отчёт](reports/developer.md) · [100 гипотез](reports/hypotheses.md)

Набор тестов для HTTP-сервиса загрузки/скачивания файлов, который проверяется
как чёрный ящик. Python-тесты (pytest + HTTPX) покрывают пользовательский цикл,
квоты и защитные свойства; сценарии k6 — нагрузку.

Адрес цели задаётся профилем или переменной окружения. Для настройки стенда используется пример
`http://files.example.com`.

## Возможности

| Каталог | Что проверяет |
|---|---|
| `tests/e2e/` | H01, L01, F01–F07, N01, N02 — health, список, загрузка/скачивание с побайтовой сверкой SHA-256, границы размера, полнота пакетной квитанции, ошибки ввода, повтор имени |
| `tests/capacity/` | C01–C05 — квота количества и суммы байтов, учёт изменений, размер каталога, прогноз ёмкости |
| `tests/security/` | SEC01–SEC06 — транспорт, заголовки выдачи, публичная схема, минимальность ошибок, гигиена секретов, конфигурация |
| `load/k6/` | P01 read-smoke, P02 mixed, P03 catalog — нагрузка с контролем SHA и кода выхода |
| `tests/harness/` | самопроверка инструментов на синтетическом дублёре (без сети) |

Покрытие по сценариям — в [`docs/coverage.md`](docs/coverage.md), контракт
компонентов — в [`docs/CONTRACT.md`](docs/CONTRACT.md).

## Быстрый старт

```sh
python3 -m pip install -r requirements.lock
python3 -m pip install -e ".[dev]"

make selftest                       # автономно, без сети
```

Запуск против стенда:

```sh
make e2e PROFILE=live               # пользовательские сценарии
make capacity PROFILE=profiles/disposable.example.json    # квоты (нужен стенд с reset/quotas)
make security PROFILE=live          # защитные свойства
make report RUN=<run-id> PROFILE=live  # HTML + Markdown отчёт
```

`make report` передаёт профиль в `tools/collect.py`: обязательные кейсы берутся
из `required.cases`. GO невозможен, если обязательный кейс отсутствует или
имеет статус skip / incomplete / observation.

## Настройка цели

Профиль — JSON со схемой `fileqa-profile` v1 (см. [`profiles/`](profiles/)).
Адрес цели задаётся одним из способов:

1. отредактировать `origin` в профиле;
2. переменной `FILEQA_ORIGIN` (переопределяет профиль);
3. переменной `FILEQA_PROFILE` (путь к другому профилю).

| Переменная | Назначение |
|---|---|
| `FILEQA_PROFILE` | путь к профилю (по умолчанию `profiles/live.json`) |
| `FILEQA_ORIGIN` | адрес цели |
| `FILEQA_RUN_ID` | идентификатор прогона (по умолчанию UTC + uuid) |
| `FILEQA_ARTIFACTS` | каталог доказательств |

Отсутствующие лимиты в профиле — `null`, неизвестная политика — `"unknown"`.
Источник каждой настройки — поле `sources` (`agreement` / `stand` /
`observation` / `assumed`).

## Манифест

Python и k6 читают один манифест (схема `fileqa-manifest` v1): объекты с
`name_sent`, `name_saved`, `url`, `bytes`, `sha256`. Размер — целое число байтов,
SHA-256 — 64 символа hex. Подготовить фикстуру и манифест:

```sh
python3 -m fileqa.prepare --profile profiles/live.json --run <id> --size 262 \
  --out artifacts/<id>/manifest.json
```

## Нагрузка k6

k6 запускается на машине с установленным k6 (версия зафиксирована в
[`docs/performance.md`](docs/performance.md)). Пример:

```sh
k6 run -e MANIFEST=/abs/path/manifest.json load/k6/scenarios/mixed.js
```

Сценарий `read-smoke.js` совместим с историческим вызовом через `FILE_URL` +
`FILE_SHA256`. Путь к манифесту передаётся абсолютным — `open()` в k6 считает
относительный путь от каталога сценария.

## CI

В [GitHub Actions](.github/workflows/fileqa.yml) на push и pull request запускаются самопроверки на локальном HTTP-дублёре. Наборы e2e, capacity и security доступны при ручном запуске workflow. Для выбранного окружения staging или disposable задайте секрет STAGING_ORIGIN с адресом соответствующего стенда. Нагрузка k6 запускается отдельно по подготовленному манифесту.


## Структура

```
src/fileqa/          пакет: клиент, конфигурация, фикстуры, манифест, доказательства
tests/harness/       самопроверка (без сети)
tests/e2e/           пользовательские сценарии
tests/capacity/      квоты и ёмкость
tests/security/      защитные свойства + бриф пентеста
load/k6/             сценарии k6
profiles/            примеры профилей
.github/workflows/   GitHub Actions
docs/                контракт, методика, покрытие, безопасность
```

## Безопасность данных

В reports/evidence/ приведены обезличенные измерения. Адрес стенда задаётся через окружение.
Результаты прогонов и доказательства — в `artifacts/` (в `.gitignore`).
Выводы внешней проверки от 24 ноября приведены в [техническом отчёте](reports/developer.md#handoff). Для повторной оценки релизной сборки подготовлен [бриф](docs/pentest-brief.md).
