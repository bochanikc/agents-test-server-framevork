# Нагрузка k6 (роль 04-k6)

Профили P01/P02/P03. Это стартовые профили измерений, не договорные SLO.
Каталог сценариев — `load/k6/`, владение роли 04-k6.

k6 на сервере (версия 2.4.0, linux/amd64) запускает оркестратор. На машине
разработчика k6 нет; здесь сценарии только готовятся и проверяются синтаксисом
(финально — `k6 inspect` на сервере). Нагрузка против живого сервиса НЕ
запускается: режим «подготовлено, запуск отложен».

## Требования к стенду

- Выделенный одноразовый экземпляр сервиса (не общий живой стенд) с
  собственным namespace, чтобы записи P02 не смешивались с чужими.
- Генератор (машина с k6) расположен в той же сети, что и сервис: та же
  подсеть/VPC, минимальные прыжки маршрутизации. Сеть фиксируется в отчёте,
  иначе сравнивать P01 с историческим прогоном нельзя.
- Манифест `fileqa-manifest` v1 с объектами-фикстурами уже подготовлен
  (см. `examples/manifest.example.json`) и указывает `origin` целевого стенда.
- Для P03 нужны снимки C04 (16 × 64 КиБ и/или 1 024 × 1 КиБ), загруженные
  владельцем в выделенный инстанс; их `name_saved` и `sha256` — в манифесте.

## P01 · read-smoke

Воспроизводит прежние серии чтения одного файла (262 байта): одна серия на
запуск, `VUS` VU × `ITERATIONS` итераций, пауза 750 мс, контроль SHA до/после.
Историческая пара «1 VU × 8» и «2 VU × 8» — это два запуска.

Автономно, через подготовленный манифест:

```bash
cd framework
k6 run -e MANIFEST=runs/<run_id>/manifest.json -e VUS=1 -e ITERATIONS=8 \
  --summary-export=runs/<run_id>/evidence/load/p01-1vu.json \
  load/k6/scenarios/read-smoke.js
k6 run -e MANIFEST=runs/<run_id>/manifest.json -e VUS=2 -e ITERATIONS=8 \
  --summary-export=runs/<run_id>/evidence/load/p01-2vu.json \
  load/k6/scenarios/read-smoke.js
```

Историческая совместимость (без манифеста, как `tools/read-profile.js`):

```bash
k6 run -e FILE_URL=http://stand/files/qa.bin \
  -e FILE_SHA256=a019739031c9d1216d0011406a69a2efcd3e9f8ddbe1ef7f8c1097bfe2c59ca6 \
  -e VUS=1 --summary-export=out.json load/k6/scenarios/read-smoke.js
```

Приоритет цели: `FILE_URL`+`FILE_SHA256` вместе, иначе `MANIFEST` (+
`OBJECT_INDEX`, по умолчанию 0). Имя check `200 + original SHA-256` сохранено
для воспроизводимости P01.

Пороги: `checks rate==1`, `http_req_failed rate==0`. `summaryTrendStats`
`min/med/p(95)/max/count`. Нарушение SHA прерывает прогон (`exec.test.abort`).

## Оракулы статуса

Проверки используют точные коды (`200` для чтения, `201` для загрузки,
`304` для условного чтения), а не диапазон `status < 500`. Транспортная
ошибка k6 (`status == 0`: таймаут, обрыв, недоступный DNS) не является
HTTP-ответом и не должна проходить проверку. Сетевые сбои видны отдельно в
`http_req_failed`, а не смешиваются с 4xx/5xx. В сводке `by_name` разделяет
`get-file` / `get-list` / `upload` / `control-download`: общая медиана по
всем операциям не заменяет распределение листинга.

## P02 · mixed

Детерминированная смесь 100 операций: 60 GET файлов, 30 GET списка,
10 POST по 64 КиБ, до 2 VU. 110 HTTP-запросов рабочей фазы (10 контрольных
скачиваний с отдельным тегом). Лимит 10 записей / 640 КиБ на весь прогон
(все VU). Имена записей уникальны: `qa-<run8>-p02-<iterationInTest>.bin`.

```bash
cd framework
k6 run -e MANIFEST=runs/<run_id>/manifest.json \
  -e SUMMARY_EXPORT=runs/<run_id>/evidence/load/p02-summary.json \
  load/k6/scenarios/mixed.js
```

Разделение метрик: name-теги `get-file` / `get-list` / `upload` /
`control-download`, phase-тег `work`/`setup`/`teardown`. Пороги считают только
`phase=work`. Нарушение целостности контрольного скачивания останавливает
записи (`exec.test.abort`) и даёт ненулевой код выхода.

Параметры (env): `MIXED_MAX_VUS` (2), `MIXED_OPERATIONS` (100),
`MIXED_POST_BYTES` (65536), `MIXED_MAX_RECORDS` (10), `MIXED_SLEEP_MS` (100).

## P03 · catalog

Одинаковое фиксированное число обходов каталога одним клиентом (10) по
манифесту C04. Проверяет ожидаемый набор собственных записей
(`objects[].name_saved`) и учитывает постраничный обход.

```bash
cd framework
k6 run -e MANIFEST=runs/<run_id>/manifest.json \
  -e CATALOG_PASSES=10 -e CATALOG_PAGE_SIZE=0 \
  -e SUMMARY_EXPORT=runs/<run_id>/evidence/load/p03-summary.json \
  load/k6/scenarios/catalog.js
```

Параметры (env): `CATALOG_PASSES` (10), `CATALOG_PAGE_SIZE` (0 — весь список
одним запросом), `CATALOG_PAGE_PARAM` (`page`), `CATALOG_MAX_REQ_PER_PASS`
(потолок запросов на обход; по умолчанию выводится из числа объектов и размера
страницы). Метрики: `catalog_first_page_ms`, `catalog_last_page_ms`,
`catalog_pass_bytes`, `catalog_missing_records`.

## Расширение длительности и arrival-rate (бюджет от владельца)

Стартовые профили — не SLO. Для измерения устойчивости владелец задаёт:
целевой пользовательский поток, длительность, диапазон размеров файлов, пределы
ресурсов генератора и критерии остановки. Расширение описывается параметризацией
env, а не правкой кода.

- Длительность: тот же `shared-iterations`, но `MIXED_OPERATIONS` и
  `MIXED_SLEEP_MS` задают бюджет. Например, 1000 операций с паузой 50 мс ≈
  бюджет ≥ 50 с плюс сетевая задержка. Бюджет владельца — в поле `budget`
  профиля `profiles/load.example.json` (`objects`, `bytes`, `seconds`).
- Arrival-rate (входящие операции/с): отдельный профиль на `constant-arrival-rate`
  с `maxVUs`, потому что `shared-iterations` не держит заданную скорость. При
  этом учитывать `dropped_iterations`: если VU не хватает, итерации отбрасываются,
  и это фиксируется отдельно. Заданные VU ≠ достигнутый RPS: VU — в `options`,
  RPS — `http_reqs.values.rate` в сводке.

## Код выхода и машинная сводка

k6 возвращает код выхода в оболочку (в CI пробрасывается автоматически):

| Код | Смысл |
|---|---|
| 0 | успех |
| 104 | сценарий прерван `exec.test.abort()` (нарушение целостности) |
| 105 | упал `setup()` |
| 107 | нарушен порог (threshold) |

read-smoke не определяет `handleSummary`, поэтому машинная сводка пишется
флагом `--summary-export` (полный JSON метрик). Ключевые поля:

- `metrics.http_req_duration.values.count` — N (число наблюдений);
- `.med`, `['p(95)']`, `.min`, `.max` — задержки в миллисекундах;
- `metrics.http_reqs.values.count` и `.rate` — запросы и достигнутый RPS (1/с);
- `metrics.http_req_failed.values.rate` — доля HTTP-ошибок;
- `metrics.checks.values.{passes,fails,rate}` и `root_group.checks[]` — каждый
  check по имени.

mixed и catalog определяют `handleSummary` и печатают JSON схемы
`fileqa-k6-summary` на stdout (и в `SUMMARY_EXPORT`, если задан): поля
`assigned_vus`, `achieved_rps`, `http_req_duration_ms.{count,min_ms,med_ms,p95_ms,max_ms}`,
`http_req_failed_rate`, `checks`, `by_name`, `custom`, блок `units`
(`duration: ms`, `rate: per_second`, `bytes: bytes`). `count` — это N.
