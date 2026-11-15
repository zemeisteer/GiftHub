import { test, before, afterEach } from 'node:test';
import assert from 'node:assert/strict';

let api, ApiError, tg;
const realFetch = globalThis.fetch;
before(async () => {
  ({ api, ApiError } = await import('./api.js'));
  ({ tg } = await import('./tg.js'));
});
afterEach(() => { globalThis.fetch = realFetch; });

function jsonRes(status, body) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

test('tg works without Telegram', () => {
  assert.equal(tg.initData, '');
  assert.equal(tg.inTelegram, false);
  assert.equal(tg.user, null);
  assert.doesNotThrow(() => { tg.ready(); tg.haptic('light'); tg.backButton(null); tg.hideMainButton(); tg.mainButton('x', () => {}); });
});

test('api attaches initData header (read at call time)', async () => {
  let seen;
  globalThis.fetch = async (url, init) => { seen = init.headers; return jsonRes(200, { ok: 1 }); };
  tg.initData = 'query_id=1';
  const r = await api('/api/x');
  assert.deepEqual(r, { ok: 1 });
  assert.equal(seen['X-Telegram-Init-Data'], 'query_id=1');
  tg.initData = 'query_id=2';
  await api('/api/x');
  assert.equal(seen['X-Telegram-Init-Data'], 'query_id=2');
  tg.initData = '';
});

test('api sends JSON body', async () => {
  let seen, url;
  globalThis.fetch = async (u, init) => { url = u; seen = init; return jsonRes(200, {}); };
  await api('/api/x', { method: 'POST', body: { a: 1 } });
  assert.equal(seen.method, 'POST');
  assert.equal(seen.body, '{"a":1}');
  assert.equal(seen.headers['Content-Type'], 'application/json');
  assert.equal(url, '/api/x');
});

test('api times out with friendly message', async () => {
  globalThis.fetch = (u, init) => new Promise((_, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  await assert.rejects(api('/x', { timeoutMs: 10 }), (e) => e instanceof ApiError && e.status === 0 && e.message === 'Server javob bermadi');
});

test('api timeout also covers the response body', async () => {
  globalThis.fetch = async (u, init) => ({
    ok: true,
    status: 200,
    text: () => new Promise((_, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }),
  });
  await assert.rejects(api('/x', { timeoutMs: 10 }), (e) => e instanceof ApiError && e.status === 0 && e.message === 'Server javob bermadi');
});

test('api maps network failure', async () => {
  globalThis.fetch = async () => { throw new TypeError('failed'); };
  await assert.rejects(api('/x'), { status: 0, message: "Internet aloqasi yo'q" });
});

test('api maps 4xx detail string', async () => {
  globalThis.fetch = async () => jsonRes(400, { detail: 'Promo-kod topilmadi' });
  await assert.rejects(api('/x'), { status: 400, message: 'Promo-kod topilmadi' });
});

test('api maps list detail to first msg', async () => {
  globalThis.fetch = async () => jsonRes(422, { detail: [{ msg: 'field required' }, { msg: 'other' }] });
  await assert.rejects(api('/x'), { status: 422, message: 'field required' });
});

test('api falls back to generic message', async () => {
  globalThis.fetch = async () => new Response('oops', { status: 500 });
  await assert.rejects(api('/x'), { status: 500, message: 'Xatolik (500)' });
});

test('api returns null on 204', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await api('/x'), null);
});

test('api rejects non same-origin paths', async () => {
  let called = false;
  globalThis.fetch = async () => { called = true; return jsonRes(200, {}); };
  for (const p of ['https://evil.com/x', '//evil.com/x', 'api/x', '/\\evil.com']) {
    await assert.rejects(api(p));
  }
  assert.equal(called, false);
});
