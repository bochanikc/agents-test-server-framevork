// Общий контракт чтения манифеста fileqa-manifest v1 для k6.
// Манифест одинаково понимается Python (fileqa.manifest) и JavaScript:
// размер объекта — целое число байтов, SHA-256 — 64 символа hex нижнего
// регистра. Секреты в манифест не попадают.

const SCHEMA = 'fileqa-manifest';
const VERSION = 1;

// Читает строку из окружения с умолчанием.
export function envStr(name, def = null) {
  const v = __ENV[name];
  return v === undefined || v === null || v === '' ? def : v;
}

// Читает неотрицательное целое из окружения с умолчанием и нижней границей.
export function envInt(name, def = 0, min = 0) {
  const raw = __ENV[name];
  if (raw === undefined || raw === null || raw === '') return def;
  const n = Number(raw);
  if (typeof n !== 'number' || !isFinite(n) || Math.floor(n) !== n || n < min) {
    throw new Error(`${name} должен быть целым числом >= ${min}, получено: ${raw}`);
  }
  return n;
}

// Строка — ровно 64 символа hex нижнего регистра.
export function isHexSha256(value) {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
}

export function originOf(manifest) {
  const origin = String(manifest.origin || '').replace(/\/+$/, '');
  if (!/^https?:\/\/[^/]+$/.test(origin)) {
    throw new Error(`манифест задаёт неверный origin: ${manifest.origin}`);
  }
  return origin;
}

// scheme + netloc из http(s)-URL. k6 не даёт конструктор URL — разбираем regex.
function schemeAndNetloc(u) {
  const m = /^(https?):\/\/([^/]+)/.exec(String(u));
  return m ? { scheme: m[1], netloc: m[2] } : null;
}

// Абсолютный URL берём только если он принадлежит origin (симметрично
// Python-клиенту client.py::_resolve); относительный путь дополняем origin.
export function resolveUrl(origin, url) {
  const s = String(url);
  if (/^https?:\/\//.test(s)) {
    const base = schemeAndNetloc(origin);
    const target = schemeAndNetloc(s);
    if (!base || !target || target.scheme !== base.scheme || target.netloc !== base.netloc) {
      throw new Error(`URL вне origin манифеста: ${s}`);
    }
    return s;
  }
  if (!s.startsWith('/')) {
    throw new Error(`URL объекта должен быть абсолютным или начинаться с "/": ${s}`);
  }
  return `${origin}${s}`;
}

// Проверяет структуру и типы так же, как Python-модуль fileqa.manifest.
export function validateManifest(m) {
  if (!m || typeof m !== 'object') throw new Error('манифест не является объектом JSON.');
  if (m.schema !== SCHEMA) throw new Error(`неизвестная схема манифеста: ${m.schema}`);
  if (m.version !== VERSION) throw new Error(`неизвестная версия манифеста: ${m.version}`);
  if (typeof m.origin !== 'string' || !m.origin.trim()) throw new Error('манифест без origin');
  if (!Array.isArray(m.objects)) throw new Error('objects должен быть массивом');
  for (const obj of m.objects) {
    if (typeof obj.bytes !== 'number' || !isFinite(obj.bytes) || Math.floor(obj.bytes) !== obj.bytes || obj.bytes < 0) {
      throw new Error(`bytes объекта не является неотрицательным целым: ${obj.name_saved}`);
    }
    if (!isHexSha256(obj.sha256)) {
      throw new Error(`sha256 объекта неверен: ${obj.name_saved}`);
    }
    if (typeof obj.url !== 'string' || !obj.url) {
      throw new Error(`объект без url: ${obj.name_saved}`);
    }
  }
}

export function loadManifest(path) {
  if (!path) {
    throw new Error('MANIFEST не задан. Укажите путь к манифесту fileqa-manifest v1 (env MANIFEST).');
  }
  let text;
  try {
    text = open(path);
  } catch (e) {
    throw new Error(
      `не удалось прочитать манифест: ${path}. ` +
      'k6 open() с относительным путём считает его от каталога сценария — передавайте АБСОЛЮТНЫЙ путь к манифесту.',
    );
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error(`манифест не является корректным JSON: ${path}`);
  }
  validateManifest(data);
  return data;
}

// Цель чтения для read-smoke: либо FILE_URL + FILE_SHA256 (исторический вызов),
// либо объект манифеста (OBJECT_INDEX переопределяет индекс, по умолчанию 0).
export function resolveDownloadTarget() {
  const url = envStr('FILE_URL');
  const sha = envStr('FILE_SHA256');
  if (url && sha) {
    if (!/^https?:\/\/[^/]+\/.+/.test(url)) {
      throw new Error('FILE_URL должна быть абсолютным URL с путём.');
    }
    if (!isHexSha256(sha)) {
      throw new Error('FILE_SHA256 должна быть 64 символами hex нижнего регистра.');
    }
    return { url, sha256: sha, bytes: -1 };
  }
  if (url || sha) throw new Error('Задайте ОБА FILE_URL и FILE_SHA256, либо путь MANIFEST.');
  const m = loadManifest(envStr('MANIFEST'));
  const idx = envInt('OBJECT_INDEX', 0, 0);
  const obj = (m.objects || [])[idx];
  if (!obj) throw new Error(`В манифесте нет объекта с индексом ${idx}.`);
  return { url: resolveUrl(originOf(m), obj.url), sha256: obj.sha256, bytes: obj.bytes };
}
