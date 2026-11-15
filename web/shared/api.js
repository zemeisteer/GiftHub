import { tg } from './tg.js';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function isSameOriginPath(p) {
  return typeof p === 'string' && p.startsWith('/') && !p.startsWith('//') && !p.startsWith('/\\') && !/[\x00-\x20\x7f]/.test(p);
}

function detailMessage(data, status) {
  const d = data && data.detail;
  if (typeof d === 'string' && d) return d;
  if (Array.isArray(d) && d[0] && typeof d[0].msg === 'string') return d[0].msg;
  return `Xatolik (${status})`;
}

export async function api(path, opts = {}) {
  if (!isSameOriginPath(path)) throw new Error('api(): only same-origin paths are allowed');
  const { method = 'GET', body, timeoutMs = 15000 } = opts;
  const headers = { 'X-Telegram-Init-Data': tg.initData || '' };
  const init = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const ctrl = new AbortController();
  init.signal = ctrl.signal;
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  let data = null;
  try {
    res = await fetch(path, init);
    // The timer stays armed until the body is read.
    if (res.status !== 204) {
      const text = await res.text();
      if (text) {
        try { data = JSON.parse(text); } catch { data = null; }
      }
    }
  } catch (e) {
    if (e && e.name === 'AbortError') throw new ApiError(0, 'Server javob bermadi');
    throw new ApiError(0, "Internet aloqasi yo'q");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, res.status));
  return data;
}
