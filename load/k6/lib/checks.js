// HTTP- и контент-проверки. Отдельные checks на статус, SHA и бизнес-результат
// (размер/структура), чтобы сбой можно было отнести к нужной категории.
import { check } from 'k6';
import crypto from 'k6/crypto';

export function sha256Hex(body) {
  return crypto.sha256(body, 'hex');
}

function bodyLength(body) {
  if (body == null) return -1;
  if (typeof body === 'string') return body.length;
  if (typeof body.byteLength === 'number') return body.byteLength;
  return -1;
}

// Проверка скачивания: статус 200, SHA полученных байтов, размер (если известен).
// Возвращает { ok, statusOk, shaOk, bytesOk }.
export function checkDownload(res, expected, prefix = 'download') {
  const statusOk = check(res, { [`${prefix} status 200`]: (r) => r.status === 200 });
  const shaOk = check(res, { [`${prefix} sha256`]: (r) => r.body != null && sha256Hex(r.body) === expected.sha256 });
  const bytesKnown = Number.isInteger(expected.bytes) && expected.bytes >= 0;
  const bytesOk = bytesKnown
    ? check(res, { [`${prefix} bytes`]: (r) => bodyLength(r.body) === expected.bytes })
    : true;
  return { ok: statusOk && shaOk && bytesOk, statusOk, shaOk, bytesOk };
}

// Проверка списка: статус 200 и JSON-массив. Возвращает { ok, rows }.
export function checkList(res, prefix = 'list') {
  const statusOk = check(res, { [`${prefix} status 200`]: (r) => r.status === 200 });
  let rows = null;
  try {
    rows = res.json();
  } catch (e) {
    rows = null;
  }
  const jsonOk = check(res, { [`${prefix} json array`]: () => Array.isArray(rows) });
  return { ok: statusOk && jsonOk, rows: jsonOk ? rows : null };
}

// Проверка квитанции загрузки: статус 201 и url первого элемента uploaded.
// Возвращает { ok, url }.
export function checkUploadReceipt(res, prefix = 'upload') {
  const statusOk = check(res, { [`${prefix} status 201`]: (r) => r.status === 201 });
  try {
    const json = res.json();
    const first = firstUploaded(json);
    const receiptOk = check(res, { [`${prefix} receipt url`]: () => !!first && typeof first.url === 'string' && first.url.length > 0 });
    return { ok: statusOk && receiptOk, url: receiptOk ? first.url : null };
  } catch (e) {
    check(res, { [`${prefix} receipt url`]: () => false });
    return { ok: false, url: null };
  }
}

// Извлекает первый элемент квитанции загрузки независимо от формы.
function firstUploaded(receipt) {
  if (receipt && typeof receipt === 'object' && Array.isArray(receipt.uploaded)) {
    return receipt.uploaded[0] || null;
  }
  if (Array.isArray(receipt)) return receipt[0] || null;
  return null;
}
