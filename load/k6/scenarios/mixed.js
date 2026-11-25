// P02 · mixed: детерминированная смесь 100 операций на выделенном стенде.
// 60 GET файлов, 30 GET списка, 10 POST по 64 КиБ, до 2 VU. Итого 110
// HTTP-запросов рабочей фазы (каждый POST + контрольное скачивание).
// Лимит 10 записей / 640 КиБ действует на весь прогон (все VU).
//
// Статус, SHA, листинг и подготовка разделены тегами и метриками:
//   name-тег HTTP-запросов: get-file / get-list / upload / control-download;
//   phase-тег: work (рабочая фаза) / setup / teardown. Пороги и сводка
//   учитывают только phase=work.
import http from 'k6/http';
import { sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { loadManifest, originOf, resolveUrl, envInt, envStr } from '../lib/manifest.js';
import { sha256Hex, checkDownload, checkList, checkUploadReceipt } from '../lib/checks.js';
import { buildSummary, summaryOutput } from '../lib/summary.js';

const MAX_VUS = envInt('MIXED_MAX_VUS', 2, 1);
const OPERATIONS = envInt('MIXED_OPERATIONS', 100, 1);
const POST_BYTES = envInt('MIXED_POST_BYTES', 65536, 1); // 64 КиБ
const MAX_RECORDS = envInt('MIXED_MAX_RECORDS', 10, 1);
const SLEEP_MS = envInt('MIXED_SLEEP_MS', 100, 0);

const manifest = loadManifest(envStr('MANIFEST'));
const origin = originOf(manifest);
const runId = String(manifest.run_id || 'run');

const N_POST = MAX_RECORDS;               // 10 записей
const N_LIST = 30;
const N_GET = OPERATIONS - N_POST - N_LIST; // 60
if (N_GET < 0) {
  throw new Error(`MIXED_OPERATIONS должен быть >= ${N_POST + N_LIST} (${N_POST + N_LIST}).`);
}
if ((manifest.objects || []).length === 0 && N_GET > 0) {
  throw new Error('Манифест без объектов: нечего читать в GET файлов. Засейте фикстуру.');
}

const runMarker = (runId.replace(/[^a-zA-Z0-9_-]/g, '') || 'run').slice(0, 8);
const ownPrefix = `qa-${runMarker}-p02-`;

const recordsCreated = new Counter('records_created');
const shaFailures = new Counter('sha_failures');
const controlDownloadFailures = new Counter('control_download_failures');

export const options = {
  scenarios: {
    mixed: {
      executor: 'shared-iterations',
      vus: MAX_VUS,
      iterations: OPERATIONS,
      maxDuration: '10m',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    'http_req_failed{phase:work}': ['rate==0'],
    sha_failures: ['count==0'],
    control_download_failures: ['count==0'],
  },
  summaryTrendStats: ['min', 'med', 'p(95)', 'max', 'count'],
};

// Подготовка вынесена из рабочей статистики: phase=setup, без check().
export function setup() {
  const h = http.get(resolveUrl(origin, '/health'), {
    timeout: '10s',
    tags: { name: 'prep-health', phase: 'setup' },
  });
  if (h.status !== 200) {
    throw new Error(`Подготовка: /health вернул ${h.status}.`);
  }
  return { origin, runId };
}

// Детерминированная раскладка: итерация 0..59 — GET файла, 60..89 — GET списка,
// 90..99 — POST + контрольное скачивание. exec.scenario.iterationInTest уникален
// по всему прогону, поэтому имена записей не сталкиваются даже между VU.
export default function () {
  const i = exec.scenario.iterationInTest;
  if (i < N_GET) {
    getFile(i);
  } else if (i < N_GET + N_LIST) {
    listFiles();
  } else {
    upload(i - N_GET - N_LIST);
  }
  if (SLEEP_MS > 0) sleep(SLEEP_MS / 1000);
}

// Контрольная проверка после прогона: итоговый список. Без check(), phase=teardown,
// чтобы не влиять на метрику checks и рабочую статистику.
export function teardown() {
  http.get(resolveUrl(origin, '/files'), {
    timeout: '10s',
    tags: { name: 'post-list', phase: 'teardown' },
  });
}

export function handleSummary(data) {
  return summaryOutput(buildSummary(data, {
    profile: 'P02',
    runId,
    vus: MAX_VUS,
    operations: OPERATIONS,
  }));
}

function getFile(i) {
  const obj = manifest.objects[i % manifest.objects.length];
  const r = http.get(resolveUrl(origin, obj.url), {
    responseType: 'binary',
    redirects: 0,
    timeout: '10s',
    tags: { name: 'get-file', phase: 'work' },
  });
  const d = checkDownload(r, { sha256: obj.sha256, bytes: obj.bytes }, 'get-file');
  if (!d.shaOk) shaFailures.add(1);
}

function listFiles() {
  const r = http.get(resolveUrl(origin, '/files'), {
    redirects: 0,
    timeout: '10s',
    tags: { name: 'get-list', phase: 'work' },
  });
  checkList(r, 'list');
}

function upload(recNo) {
  const name = `${ownPrefix}${exec.scenario.iterationInTest}.bin`;
  const bytes = buildPayload(POST_BYTES, recNo);
  const sha = sha256Hex(bytes);
  const r = http.post(resolveUrl(origin, '/files'), {
    file: http.file(bytes, name, 'application/octet-stream'),
  }, {
    redirects: 0,
    timeout: '15s',
    tags: { name: 'upload', phase: 'work' },
  });
  const receipt = checkUploadReceipt(r, 'upload');
  if (!receipt.ok) {
    controlDownloadFailures.add(1);
    return;
  }
  recordsCreated.add(1);
  if (!receipt.url) {
    controlDownloadFailures.add(1);
    return;
  }
  // Контрольное скачивание принятого файла — отдельный тег.
  const d = http.get(resolveUrl(origin, receipt.url), {
    responseType: 'binary',
    redirects: 0,
    timeout: '10s',
    tags: { name: 'control-download', phase: 'work' },
  });
  const c = checkDownload(d, { sha256: sha, bytes: POST_BYTES }, 'control-download');
  if (!c.ok) {
    controlDownloadFailures.add(1);
    if (!c.shaOk) shaFailures.add(1);
    exec.test.abort(
      'Нарушение целостности: контрольное скачивание не совпало с отправленными байтами. Записи остановлены.',
    );
  }
}

// Детерминированная бинарная фикстура (как Python fileqa.fixtures.binary_payload):
// та же формула байтов и NUL/CRLF в начале, чтобы проверка целостности не
// проходила случайно на текстовых нормализациях.
function buildPayload(size, seed) {
  const b = new Uint8Array(size);
  for (let i = 0; i < size; i++) b[i] = (seed + i * 131 + i * i * 17) & 0xFF;
  if (size >= 8) {
    b[0] = 0x00;
    b[1] = 0x0D;
    b[2] = 0x0A;
    b[3] = 0x00;
  }
  return b.buffer;
}
