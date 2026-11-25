// P01 · read-smoke: воспроизведение прежних серий чтения одного файла.
// Одна серия на запуск: VUS VU × ITERATIONS итераций чтения ОДНОГО файла
// (262 байта в исторической фикстуре), пауза 750 мс, контроль SHA до/после.
// Две исторические серии (1 VU × 8 и 2 VU × 8) получаются двумя запусками
// с VUS=1 и VUS=2.
//
// Цель чтения: FILE_URL + FILE_SHA256 (исторический вызов) либо объект
// манифеста (MANIFEST, OBJECT_INDEX). Совместим с прежним вызовом:
//   k6 run -e FILE_URL=... -e FILE_SHA256=... -e VUS=1 \
//     --summary-export=out.json load/k6/scenarios/read-smoke.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { envInt, resolveDownloadTarget } from '../lib/manifest.js';

const VUS = envInt('VUS', 1, 1);
const ITERATIONS = envInt('ITERATIONS', 8, 1);
const target = resolveDownloadTarget();

export const options = {
  scenarios: {
    download: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: ITERATIONS,
      maxDuration: '45s',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate==0'],
  },
  summaryTrendStats: ['min', 'med', 'p(95)', 'max', 'count'],
};

export default function () {
  const r = http.get(target.url, {
    responseType: 'binary',
    timeout: '5s',
    redirects: 0,
    tags: { name: 'own-download' },
  });
  // Историческое имя check сохранено для воспроизводимости P01 (combined_check).
  const ok = check(r, {
    '200 + original SHA-256': (x) =>
      x.status === 200 && x.body !== null && crypto.sha256(x.body, 'hex') === target.sha256,
  });
  if (!ok) {
    exec.test.abort('Ошибка штатного чтения. Сохраните результат и проверьте одиночный контроль.');
  }
  sleep(0.75);
}
