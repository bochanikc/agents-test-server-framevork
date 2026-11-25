// P03 · catalog: одинаковое фиксированное число обходов каталога (по умолчанию
// 10 одним клиентом) по манифесту C04. Проверяет ожидаемый набор собственных
// записей (objects[].name_saved) и учитывает постраничный обход.
//
// Параметры страниц и верхняя граница запросов/объёма на обход фиксируются:
//   CATALOG_PAGE_SIZE=0  -> список целиком за один запрос (по умолчанию);
//   CATALOG_PAGE_SIZE>0  -> GET /files?page=N&limit=SIZE до последней страницы;
//   CATALOG_MAX_REQ_PER_PASS -> потолок числа запросов на обход.
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';
import { loadManifest, originOf, resolveUrl, envInt, envStr } from '../lib/manifest.js';
import { buildSummary, summaryOutput } from '../lib/summary.js';

const PASSES = envInt('CATALOG_PASSES', 10, 1);
const PAGE_SIZE = envInt('CATALOG_PAGE_SIZE', 0, 0);
const PAGE_PARAM = envStr('CATALOG_PAGE_PARAM', 'page');

const manifest = loadManifest(envStr('MANIFEST'));
const origin = originOf(manifest);
const expectedNames = (manifest.objects || []).map((o) => String(o.name_saved));
if (expectedNames.length === 0) {
  throw new Error('Манифест без объектов: нечего проверять в каталоге.');
}

const derivedMax = PAGE_SIZE > 0
  ? Math.ceil(expectedNames.length / PAGE_SIZE) * 2 + 5
  : 2;
const MAX_REQ_PER_PASS = envInt('CATALOG_MAX_REQ_PER_PASS', derivedMax, 1);

const passes = new Counter('catalog_passes');
const listRequests = new Counter('catalog_list_requests');
const missingRecords = new Counter('catalog_missing_records');
const firstPageMs = new Trend('catalog_first_page_ms');
const lastPageMs = new Trend('catalog_last_page_ms');
const passBytes = new Trend('catalog_pass_bytes');

export const options = {
  scenarios: {
    catalog: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: PASSES,
      maxDuration: '10m',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    'http_req_failed{phase:work}': ['rate==0'],
    catalog_missing_records: ['count==0'],
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
  return { origin };
}

// Один полный обход за итерацию. Обход либо один запрос (PAGE_SIZE=0), либо
// постраничный до последней страницы, но не более MAX_REQ_PER_PASS запросов.
export default function () {
  const seen = new Set();
  let reqs = 0;
  let page = 1;
  let totalBytes = 0;
  let firstMs = null;
  let lastMs = null;

  while (reqs < MAX_REQ_PER_PASS) {
    const r = http.get(listUrl(page), {
      redirects: 0,
      timeout: '10s',
      tags: { name: 'catalog-list', phase: 'work' },
    });
    reqs += 1;
    listRequests.add(1);
    lastMs = r.timings.duration;
    if (firstMs == null) firstMs = r.timings.duration;

    const statusOk = check(r, { 'catalog status 200': (x) => x.status === 200 });
    if (!statusOk) break;

    totalBytes += r.body ? r.body.length : 0;

    let rows = null;
    try {
      rows = r.json();
    } catch (e) {
      rows = null;
    }
    const jsonOk = check(r, { 'catalog json array': () => Array.isArray(rows) });
    if (!jsonOk) break;

    for (const row of rows) {
      if (row && typeof row.name === 'string') seen.add(row.name);
    }

    if (PAGE_SIZE <= 0) break;          // весь список в одном ответе
    if (rows.length < PAGE_SIZE) break; // последняя страница
    page += 1;
  }

  // Ожидаемый набор собственных записей по манифесту.
  let missing = 0;
  for (let i = 0; i < expectedNames.length; i++) {
    const name = expectedNames[i];
    const ok = seen.has(name);
    check(seen, { [`catalog object ${i}`]: (s) => s.has(name) });
    if (!ok) missing += 1;
  }
  missingRecords.add(missing);
  passes.add(1);
  firstPageMs.add(firstMs || 0);
  lastPageMs.add(lastMs || 0);
  passBytes.add(totalBytes);
}

export function handleSummary(data) {
  return summaryOutput(buildSummary(data, {
    profile: 'P03',
    runId: String(manifest.run_id || 'run'),
    vus: 1,
    operations: PASSES,
  }));
}

function listUrl(page) {
  const base = resolveUrl(origin, '/files');
  if (PAGE_SIZE <= 0) return base;
  return `${base}?${PAGE_PARAM}=${page}&limit=${PAGE_SIZE}`;
}
