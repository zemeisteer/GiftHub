import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let getView, adminState, tg, NAV;
let fetchLog;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const ALL = ['PRICING_READ', 'PRICING_UPDATE', 'SETTINGS_READ'];

function jsonRes(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
function stubFetch(routes) {
  fetchLog = [];
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method || 'GET';
    fetchLog.push({ url, method, body: init.body ? JSON.parse(init.body) : undefined });
    const path = url.split('?')[0];
    let r = routes[`${method} ${path}`];
    if (r === undefined && method === 'GET') r = routes[path];
    if (r === undefined) return jsonRes(404, { detail: 'not found' });
    if (typeof r === 'function') {
      const out = await r(init, url);
      return out instanceof Response ? out : jsonRes(200, out);
    }
    return jsonRes(200, r);
  };
}
const calls = (re) => fetchLog.filter((c) => re.test(`${c.method} ${c.url}`));
const lastBody = () => fetchLog.filter((c) => c.method !== 'GET').pop().body;

before(async () => {
  globalThis.__GIFTHUB_TEST__ = true;
  const dom = parseHTML(html);
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.Node = dom.Node;
  globalThis.Event = dom.Event;
  globalThis.location = { hash: '' };
  ({ getView, adminState } = await import('./registry.js'));
  await import('./views/gifts.js');
  ({ NAV } = await import('./nav.js'));
  ({ tg } = await import('../shared/tg.js'));
});

beforeEach(() => {
  tg.resetOverrides();
  tg.inTelegram = true;
  tg.initData = 'query_id=1';
  adminState.admin = { id: 1, role: 'super_admin', permissions: ALL };
  document.body.textContent = '';
  stubFetch({});
});
afterEach(async () => {
  const open = q('.confirm-overlay .btn-secondary');
  if (open) { fire(open); await tick(2); }
  tg.resetOverrides();
});

const tick = (ms = 10) => new Promise((r) => setTimeout(r, ms));
const q = (sel) => document.querySelector(sel);
const qa = (sel) => [...document.querySelectorAll(sel)];
const btn = (label) => qa('button').find((b) => b.textContent.trim() === label);
const fire = (el, type = 'click') => el.dispatchEvent(new Event(type, { bubbles: true }));
const click = (label) => {
  const b = btn(label);
  assert.ok(b, `button "${label}" not found`);
  fire(b);
};
const input = (name) => q(`[name="${name}"]`);
const setField = (name, value) => {
  const el = input(name);
  assert.ok(el, `field ${name} not found`);
  el.value = String(value);
};
async function mount(id) {
  const node = await getView(id)({ id });
  const outlet = document.createElement('main');
  outlet.appendChild(node);
  document.body.appendChild(outlet);
  await tick(15);
  return outlet;
}
const dialogText = () => (q('[role="dialog"]') || { textContent: '' }).textContent;
async function confirmYes() {
  assert.ok(q('[role="dialog"]'), 'confirm dialog expected');
  fire(q('.confirm-actions .btn:last-child'));
  await tick();
}
const hasText = (s) => document.body.textContent.includes(s);

const gift = (over = {}) => ({
  id: '5170145012310081615', emoji: '💝', title: null, name: "15 ⭐ sovg'a", star_count: 15,
  price_uzs: 4200, cost_uzs: 3000, price_override_uzs: null, enabled: true, available: true,
  is_limited: false, remaining_count: null, is_premium: false, synced_at: '2026-11-20T10:00:00+00:00', ...over,
});
const DATA = (over = {}, gifts = [gift()]) => ({
  gifts, bot_star_balance: 1500, reserved_stars: 200, last_sync_at: '2026-11-20T10:00:00+00:00',
  last_sync_error: null, low_balance: false, ...over,
});
const ID = '5170145012310081615';

test('gifts view lists rows with effective price and balance', async () => {
  stubFetch({ '/api/admin/gifts': DATA({}, [gift({ price_override_uzs: 5000, price_uzs: 5000, title: 'Yurak', name: 'Yurak' })]) });
  await mount('gifts');
  assert.ok(hasText('Botning Stars balansi: 1500 ⭐'));
  assert.ok(hasText('zaxirada: 200 ⭐'));
  assert.ok(hasText('💝'));
  assert.ok(hasText('Yurak'));
  assert.ok(hasText('15 ⭐'));
  assert.ok(hasText('5 000'));
  assert.equal(input(`title_${ID}`).value, 'Yurak');
  assert.equal(input(`override_${ID}`).value, '5000');
  assert.equal(q('[role="switch"]').getAttribute('aria-checked'), 'true');
  assert.equal(q('.gift-warning'), null);
});

test('low balance shows warning', async () => {
  stubFetch({ '/api/admin/gifts': DATA({ low_balance: true, bot_star_balance: 20 }) });
  await mount('gifts');
  assert.ok(q('.gift-warning'));
  assert.match(q('.gift-warning').textContent, /Stars/);
});

test('badges: premium, limited remaining, unavailable on Telegram', async () => {
  stubFetch({ '/api/admin/gifts': DATA({}, [
    gift({ is_premium: true }),
    gift({ id: 'b', is_limited: true, remaining_count: 7, available: false }),
  ]) });
  await mount('gifts');
  assert.ok(hasText('Premium'));
  assert.ok(hasText("Telegram'da yo'q"));
  assert.ok(hasText('Qoldiq: 7'));
});

test('sync button posts once and refetches (double click = one request)', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({
    '/api/admin/gifts': DATA(),
    'POST /api/admin/gifts/sync': async () => { await gate; return { success: true, added: 1, updated: 0, unavailable: 0 }; },
  });
  await mount('gifts');
  click('Sinxronlash');
  click('Sinxronlash');
  await tick();
  release();
  await tick(20);
  assert.equal(calls(/POST \/api\/admin\/gifts\/sync/).length, 1);
  assert.equal(calls(/^GET \/api\/admin\/gifts/).length, 2);
});

test('price override save asks danger confirm showing old and new and sends PATCH with number', async () => {
  stubFetch({
    '/api/admin/gifts': DATA({}, [gift({ price_override_uzs: 5000, price_uzs: 5000 })]),
    [`PATCH /api/admin/gifts/${ID}`]: gift({ price_override_uzs: 6500, price_uzs: 6500 }),
  });
  await mount('gifts');
  setField(`override_${ID}`, '6500');
  click('Narxni saqlash');
  await tick();
  assert.match(dialogText(), /5 000/);
  assert.match(dialogText(), /6 500/);
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/PATCH/).length, 0);
  await confirmYes();
  await tick(15);
  assert.equal(calls(/PATCH/).length, 1);
  assert.deepEqual(lastBody(), { price_override_uzs: 6500 });
  assert.equal(typeof lastBody().price_override_uzs, 'number');
  assert.equal(calls(/^GET \/api\/admin\/gifts/).length, 2);
});

test('clearing override sends null', async () => {
  stubFetch({
    '/api/admin/gifts': DATA({}, [gift({ price_override_uzs: 5000, price_uzs: 5000 })]),
    [`PATCH /api/admin/gifts/${ID}`]: gift(),
  });
  await mount('gifts');
  setField(`override_${ID}`, '');
  click('Narxni saqlash');
  await tick();
  assert.match(dialogText(), /5 000/);
  await confirmYes();
  assert.deepEqual(lastBody(), { price_override_uzs: null });
});

test('unchanged override sends nothing; negative is blocked client-side', async () => {
  stubFetch({ '/api/admin/gifts': DATA() });
  await mount('gifts');
  click('Narxni saqlash');
  await tick();
  assert.ok(!q('[role="dialog"]'));
  setField(`override_${ID}`, '-5');
  click('Narxni saqlash');
  await tick();
  assert.ok(!q('[role="dialog"]'));
  assert.equal(calls(/PATCH/).length, 0);
  assert.ok(q('.field-error') && !q('.field-error').hasAttribute('hidden'));
});

test('title save sends trimmed title, empty clears with null', async () => {
  stubFetch({ '/api/admin/gifts': DATA({}, [gift({ title: 'Eski', name: 'Eski' })]), [`PATCH /api/admin/gifts/${ID}`]: gift() });
  await mount('gifts');
  setField(`title_${ID}`, '  Yangi  ');
  click('Nomni saqlash');
  await tick();
  await confirmYes();
  assert.deepEqual(lastBody(), { title: 'Yangi' });
  await tick(15);
  setField(`title_${ID}`, '');
  click('Nomni saqlash');
  await tick();
  await confirmYes();
  assert.deepEqual(lastBody(), { title: null });
});

test('toggle asks plain confirm and sends enabled', async () => {
  stubFetch({ '/api/admin/gifts': DATA(), [`PATCH /api/admin/gifts/${ID}`]: gift({ enabled: false }) });
  await mount('gifts');
  fire(q('[role="switch"]'));
  await tick();
  assert.ok(q('[role="dialog"]'));
  assert.equal(calls(/PATCH/).length, 0);
  await confirmYes();
  assert.deepEqual(lastBody(), { enabled: false });
});

test('server 400 on override below cost is shown', async () => {
  const msg = "Narx tannarxdan past bo'lishi mumkin emas (tannarx: 3000 so'm).";
  stubFetch({
    '/api/admin/gifts': DATA(),
    [`PATCH /api/admin/gifts/${ID}`]: () => jsonRes(400, { detail: msg }),
  });
  await mount('gifts');
  setField(`override_${ID}`, '100');
  click('Narxni saqlash');
  await tick();
  await confirmYes();
  await tick(15);
  assert.equal(q('#toast').textContent, msg);
});

test('titles and emoji from Telegram are rendered as text', async () => {
  const evil = '<img src=x onerror=alert(1)>';
  stubFetch({ '/api/admin/gifts': DATA({}, [gift({ title: evil, name: evil, emoji: '<b>x</b>' })]) });
  await mount('gifts');
  assert.ok(hasText(evil));
  assert.equal(qa('img').length, 0);
  assert.equal(qa('b').some((b) => b.textContent === 'x'), false);
});

test('read-only admin cannot edit', async () => {
  adminState.admin = { id: 1, permissions: ['PRICING_READ'] };
  stubFetch({ '/api/admin/gifts': DATA() });
  await mount('gifts');
  assert.equal(btn('Sinxronlash'), undefined);
  assert.equal(btn('Narxni saqlash'), undefined);
  assert.equal(btn('Nomni saqlash'), undefined);
  assert.ok(q('[role="switch"]').hasAttribute('disabled'));
  assert.ok(input(`override_${ID}`).hasAttribute('disabled'));
  assert.ok(input(`title_${ID}`).hasAttribute('disabled'));
});

test("nav lists Sovg'alar in Savdo group", () => {
  const savdo = NAV.find((g) => g.group === 'Savdo');
  assert.deepEqual(savdo.items.map((i) => i.id), ['pricing', 'services', 'gifts', 'promos', 'referral']);
  assert.deepEqual(savdo.items[2], { id: 'gifts', label: "Sovg'alar", icon: 'gift', perm: 'PRICING_READ' });
});
