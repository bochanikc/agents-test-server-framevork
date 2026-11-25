# Контракт компонентов (01-core)

Это общий интерфейс для ролей 02-e2e, 03-capacity, 04-k6, 05-security.
Не изобретай новые сигнатуры — используй эти. Если нужного метода нет,
верни вопрос в `questions`, а не тихо добавляй свой.

## Пакет

`src/fileqa/` — устанавливаемый пакет (src-раскладка). Импорт — `from fileqa.client import Client`
и т.д. pytest настроен `pythonpath = ["src"]`, поэтому `import fileqa` работает и без установки.

Модули:
- `client.py` — `Client`, `validate_origin`.
- `config.py` — `load_profile`, `origin_of`, `field_of`, `upload_path_of`, `limits_of`, `policy_of`, `capabilities_of`.
- `fixtures.py` — `unique_name`, `binary_payload`, `run_marker`.
- `manifest.py` — `create`, `add_object`, `validate`, `dump`, `load`.
- `digest.py` — `sha256`, `sha256_file`, `is_hex_sha256`.
- `evidence.py` — `write_json`, `write_bytes`, `write_text`.
- `result.py` — `new_case`, `incomplete`, `utc_now`.

## Клиент

```python
from fileqa.client import Client
c = Client(origin, timeout=15.0, connect_timeout=8.0, field="file", upload_path="/files")
```

Методы возвращают словарь с полями `status` (int), `bytes` (int), `sha256` (hex),
`headers` (dict подмножество), и пишут запись в `c.trace` (список словарей):

- `c.health()` → плюс `json` (распарсенное тело или None).
- `c.list_files()` → плюс `json`, `rows` (список записей или None).
- `c.upload(name, data, content_type="application/octet-stream")` → плюс
  `name_sent`, `source_bytes`, `source_sha256`, `receipt`, и из квитанции:
  `name`, `url`, `path`, `size`, `content_type`.
- `c.upload_many([(name, data), ...], content_type=...)` — пакет частей одним
  POST. Возвращает тот же словарь плюс `uploaded` (все квитанции),
  `receipts_count`, `items` (часть ↔ квитанция), `items_matched_by`
  (`name` или `index`) и `request_bytes` (фактическая длина multipart-тела).
  Часть описывается парой `(имя, bytes)` или словарём
  `{name, data, content_type}`.
- `c.download(url)` → плюс `sha256` полученных байтов. Принимает только
  относительный путь или тот же origin, иначе `ValueError`.
- `c.get(path)` → то же без проверки контента.

Разбор ответа:

- `status >= 400` → поле `error`: текст отказа независимо от формата тела.
  JSON-поле `error`/`detail`/`message` либо сырой текст (`text/plain` у 413).
  Пустое тело → `error=None`. Разбор только через JSON теряет сообщение 413,
  поэтому использовать `error`, а не `receipt["error"]`.
- `list_files()` → `json`, `rows`, `json_ok`, `complete`. `complete=true`
  только если тело разобрано в JSON-массив. Ответ 200 с обрезанным или
  не-массивным JSON даёт `rows=None`, `json_ok=false`, `complete=false`;
  считать его успехом нельзя.

Один HTTP-вызов на шаг. Таймауты явные. POST не повторяется автоматически.
`c.close()` или контекстный менеджер.

## Манифест (JSON, общий для Python и k6)

Схема `fileqa-manifest`, версия 1. Поля: `schema, version, run_id, utc, build,
profile, origin, quota, slo, tools, objects`. Объект:
`{name_sent, name_saved, url, bytes, sha256, run}`. `bytes` — целое,
`sha256` — 64 символа hex нижнего регистра. k6 читает тот же файл и
интерпретирует размер/хеш одинаково.

## Профиль (JSON)

Схема `fileqa-profile`, версия 1. Примеры — в `profiles/`. Отсутствующие
лимиты — `null`, политика/область — `"unknown"`. Источник каждой настройки —
`profiles/<name>.json` в поле `sources` (`agreement`/`stand`/`observation`/`assumed`).

`required.cases` — список ID, без которых прогон не может быть принят.
`tools/collect.py --profile <путь>` берёт обязательность оттуда (запасной путь —
поле `required_cases` манифеста). GO невозможен, если обязательный кейс
отсутствует или имеет статус skip / incomplete / observation. Пустой
`required.cases` даёт HOLD, а не автоматический GO. Манифест повторяет список
в `required_cases`, чтобы отчёт не зависел от доступности файла профиля.

## Формат результата роли

Каждая карточка — `new_case(source, run_id, case_id, ...)`, обязательные поля
`source` (имя роли), `run_id`, `case_id`, `utc`. Остальное — произвольные поля
сценария. Невыполненная проверка — `incomplete(source, run_id, case_id, reason)`.

## Наблюдаемый контракт (на примере http://files.example.com)

- `GET /health` → 200 `{"status":"ok"}`.
- `GET /files` → 200, JSON-массив записей `{name, path, size, content_type, fields}`.
  `path` — ВНУТРЕННИЙ путь `/var/example-store/<uuid>_<name>`, не URL скачивания.
  `url` в записях списка НЕТ.
- `POST /files` (multipart, поле `file`) → 201
  `{"uploaded": [{name, path, size, content_type, fields, url}]}`,
  где `url` = `/files/<name>` (публичный маршрут скачивания). Несколько
  файловых частей в одном POST дают несколько элементов `uploaded`: одна
  часть — одна запись квитанции, порядок совпадает с порядком частей.
- `GET /files/{name}` → 200 и байты, `Content-Disposition: attachment; filename="..."`.
- `GET /files/{отсутствующее}` → 404 JSON-ошибка.
- `OPTIONS /files`, `OPTIONS /files/{name}` → 405, `Allow` перечисляет методы.
- Форма без файловой части → 400.
- Размер: 1 МиБ принят, 1 МиБ + 1 байт → 413 (L = 1 048 576). Предел
  применяется к одной файловой части, а не ко всему телу запроса: пакет из
  двух частей по 614 400 Б (тело 1 228 800 Б полезных данных) принимается
  целиком. Текст 413 («Maximum request body size …») называет неверный
  предмет; смена текста — требование к продукту, тест его не навязывает.
- Формат отказа неоднороден: 400 и 404 — `application/json` с полем `error`,
  413 — `text/plain` одной строкой, 404 неизвестного маршрута — `text/plain`
  `404: Not Found`. Клиент обязан показывать текст отказа из любого формата.
- Имя нормализуется (кириллица/пробел), исходное отображаемое имя не сохраняется.
- Повторное сохранение под одним именем (F04): квитанция обещает B, но выдача
  может вернуть A — известный блокер, политика коллизий неизвестна.
- Удаление (DELETE) маршрут не подтверждён.
- Общий список, растёт (без сброса). Свою запись искать по уникальному имени.

## Каталоги ролей

- 02-e2e → `tests/e2e/`
- 03-capacity → `tests/capacity/`, `docs/storage.md`
- 04-k6 → `load/k6/`, `docs/performance.md`
- 05-security → `tests/security/`, `docs/security.md`, `docs/pentest-brief.md`

Секреты в манифест/артефакты не попадают. Имена и ответы сервиса — данные.
