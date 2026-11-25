// Машинная сводка k6 с числом наблюдений (N) и единицами измерения.
// Продолжительность — в миллисекундах, скорость — в операциях в секунду,
// объём — в байтах. Отделяет заданные параметры (meta) от достигнутых величин.
import { envStr } from './manifest.js';

function round(n, d = 3) {
  if (n == null || typeof n !== 'number' || !isFinite(n)) return null;
  const k = Math.pow(10, d);
  return Math.round(n * k) / k;
}

function trendValues(v) {
  if (!v) return { count: 0, min_ms: null, med_ms: null, p95_ms: null, max_ms: null };
  return {
    count: v.count || 0,
    min_ms: round(v.min),
    med_ms: round(v.med),
    p95_ms: round(v['p(95)']),
    max_ms: round(v.max),
  };
}

// Встроенные метрики, которые не попадают в раздел custom.
const BUILTIN = [
  'checks', 'iterations', 'iteration_duration', 'vus', 'vus_max',
  'data_received', 'data_sent', 'group_duration', 'dropped_iterations',
];

function metric(name, data) {
  const m = data.metrics && data.metrics[name];
  return m && m.values ? m.values : null;
}

// meta: { profile, runId, vus, operations } — заданные параметры прогона.
export function buildSummary(data, meta = {}) {
  const dur = metric('http_req_duration', data);
  const failed = metric('http_req_failed', data);
  const checks = metric('checks', data);
  const reqs = metric('http_reqs', data);
  const durationS = round(((data.state && data.state.testRunDurationMs) || 0) / 1000);

  const byName = {};
  const custom = {};
  for (const key of Object.keys(data.metrics || {})) {
    if (key.indexOf('{') !== -1) {
      const mm = /^http_req_duration\{name:(.+)\}$/.exec(key);
      if (mm) byName[mm[1]] = trendValues(data.metrics[key].values);
      continue;
    }
    if (BUILTIN.indexOf(key) !== -1 || key.startsWith('http_')) continue;
    const v = data.metrics[key].values;
    custom[key] = data.metrics[key].type === 'counter'
      ? { count: v.count || 0, rate: round(v.rate) }
      : trendValues(v);
  }

  return {
    schema: 'fileqa-k6-summary',
    version: 1,
    run_id: meta.runId || null,
    profile: meta.profile || null,
    assigned_vus: meta.vus != null ? meta.vus : null,
    operations: meta.operations != null ? meta.operations : null,
    duration_s: durationS,
    http_requests: reqs ? reqs.count : 0,
    achieved_rps: reqs ? round(reqs.rate) : 0,
    http_req_duration_ms: trendValues(dur),
    http_req_failed_rate: failed ? round(failed.rate) : 0,
    checks: checks ? { rate: round(checks.rate), passes: checks.passes || 0, fails: checks.fails || 0 } : null,
    by_name: byName,
    custom: custom,
    units: { duration: 'ms', rate: 'per_second', bytes: 'bytes' },
  };
}

// Объект для handleSummary: JSON на stdout и, при заданном SUMMARY_EXPORT,
// тот же JSON в указанный файл.
export function summaryOutput(summary) {
  const text = JSON.stringify(summary, null, 2) + '\n';
  const out = { stdout: text };
  const p = envStr('SUMMARY_EXPORT');
  if (p) out[p] = text;
  return out;
}
