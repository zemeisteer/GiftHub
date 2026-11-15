import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let barChart, getView, getBadge, adminState, tg;
let fetchLog;

const html = readFileSync(new URL('./new.html', import.meta.url), 'utf8');
const ALL = [
  'USERS_READ', 'ORDERS_READ', 'ORDERS_UPDATE', 'ORDERS_REFUND', 'PRICING_READ', 'PRICING_UPDATE',
  'PAYMENTS_READ', 'ANALYTICS_READ', 'ADMINS_READ', 'ADMINS_MANAGE', 'SETTINGS_READ', 'SETTINGS_UPDATE',
];

function jsonRes(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

// routes: 'METHOD /path' or '/path' (GET) -> body | (init, url) => Response | body
function stubFetch(routes) {
  fetchLog = [];
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method || 'GET';
    fetchLog.push({ url, method, headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : undefined });
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
const lastUrl = () => fetchLog[fetchLog.length - 1].url;
const calls = (re) => fetchLog.filter((c) => re.test(`${c.method} ${c.url}`));

before(async () => {
  globalThis.__GIFTHUB_TEST__ = true;
  const dom = parseHTML(html);
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.Node = dom.Node;
  globalThis.Event = dom.Event;
  globalThis.location = { hash: '' };
  ({ getView, getBadge, adminState } = await import('./registry.js'));
  ({ barChart } = await import('./chart.js'));
  await import('./views/dash.js');
  await import('./views/orders.js');
  await import('./views/users.js');
  await import('./views/payments.js');
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
  // A test may leave a dialog open; cancel it so its action lock is released for the next test.
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
async function mount(id) {
  const node = await getView(id)({ id });
  const outlet = document.createElement('main');
  outlet.appendChild(node);
  document.body.appendChild(outlet);
  await tick(15); // lets the non-awaited attention section settle
  return outlet;
}
async function confirmYes(label = 'Tasdiqlash') {
  assert.ok(q('[role="dialog"]'), 'confirm dialog expected');
  click(label);
  await tick();
}

const PROBLEMS = {
  success: true,
  counts: { total_problematic: 3, paid_not_fulfilled: 2, failed_fulfillment: 1 },
  orders: [1, 2, 3].map((i) => ({
    id: i, order_code: `GH-00000${i}`, user_id: 10 + i, item_title: 'Stars 100', amount: 100,
    total_price: 25000, currency: 'UZS', status: 'paid', fulfillment_status: 'pending',
    problem_detail: `Sabab ${i}`, created_at: '2026-11-15T10:00:00Z',
  })),
};
const STATS = {
  users_total: 50, new_users_week: 7, sales_total: 1234500, profit_total: 234500, ref_sales_count: 4,
  breakdown: [
    { name: 'Stars (jami)', sales: 1000000, cost: 800000, profit: 200000 },
    { name: 'Premium (jami)', sales: 200000, cost: 170000, profit: 30000 },
    { name: "Sovg'alar (jami)", sales: 34500, cost: 30000, profit: 4500 },
  ],
  charts: {
    daily: Array.from({ length: 6 }, (_, i) => ({ label: `d${i}`, sales: i * 1000, count: i })),
    weekly: Array.from({ length: 7 }, (_, i) => ({ label: `w${i}`, sales: i * 2000, count: i })),
    monthly: Array.from({ length: 4 }, (_, i) => ({ label: `m${i}`, sales: i * 3000, count: i })),
  },
};
const dashRoutes = (extra = {}) => ({
  '/api/admin/stats': STATS,
  '/api/v1/admin/orders/problematic': PROBLEMS,
  ...extra,
});

// ---- chart ----
const bars = (svg) => [...svg.querySelectorAll('rect.bar')];

test('barChart scales to the max value', () => {
  const s = barChart([{ label: 'Du', value: 5 }, { label: 'Se', value: 10 }], { height: 60 });
  assert.equal(bars(s).length, 2);
  assert.equal(bars(s)[1].getAttribute('height'), '60');
  assert.equal(bars(s)[0].getAttribute('height'), '30');
  assert.match(s.textContent, /Du/);
});

test('barChart survives empty, zero and garbage values', () => {
  assert.equal(bars(barChart([], {})).length, 0);
  const s = barChart([{ label: 'a', value: 0 }, { label: 'b', value: 'x' }, { label: 'c', value: -3 }], { height: 40 });
  for (const b of bars(s)) assert.equal(b.getAttribute('height'), '0');
});

test('barChart labels are text, not markup', () => {
  const s = barChart([{ label: '<img src=x onerror=alert(1)>', value: 1 }], {});
  assert.equal(s.querySelector('img'), null);
  assert.match(s.textContent, /<img/);
});

// ---- dashboard ----
test('dash renders KPIs, attention, chart, top products, profit table in spec order', async () => {
  stubFetch(dashRoutes());
  const o = await mount('dash');
  const order = ['.kpis', '.attention-list', '.chart-card', '.top-products', '.profit-table']
    .map((sel) => o.innerHTML.indexOf(sel.slice(1)));
  assert.ok(order.every((i) => i >= 0), JSON.stringify(order));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  assert.equal(qa('.kpi').length, 4);
  assert.match(o.textContent, /1 234 500 so'm/);
  assert.match(o.textContent, /234 500 so'm/);
  assert.match(o.textContent, /E'tibor talab qiladi/);
  assert.equal(lastUrl().includes('problematic'), true);
});

test('dash period switch swaps the chart series without refetching', async () => {
  stubFetch(dashRoutes());
  await mount('dash');
  const before = fetchLog.length;
  assert.equal(bars(q('.chart-card svg')).length, 7);
  click('Bugun');
  assert.equal(bars(q('.chart-card svg')).length, 6);
  click('30 kun');
  assert.equal(bars(q('.chart-card svg')).length, 4);
  click('7 kun');
  assert.equal(bars(q('.chart-card svg')).length, 7);
  assert.equal(fetchLog.length, before);
  assert.equal(btn('7 kun').getAttribute('aria-pressed'), 'true');
});

test('period selector lives in the chart card and does not touch the KPIs', async () => {
  stubFetch(dashRoutes());
  await mount('dash');
  assert.ok(q('.chart-card .period'));
  assert.equal(q('.kpis .period'), null);
  assert.match(q('.chart-card').textContent, /Grafik davri/);
  const kpisBefore = q('.kpis').textContent;
  click('Bugun');
  click('30 kun');
  assert.equal(q('.kpis').textContent, kpisBefore);
  assert.equal(calls(/stats/).length, 1);
});

test('dash paints KPIs and chart before the attention request finishes', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch(dashRoutes({ '/api/v1/admin/orders/problematic': async () => { await gate; return PROBLEMS; } }));
  const node = await getView('dash')({ id: 'dash' });
  document.body.appendChild(node);
  assert.equal(qa('.kpi').length, 4);
  assert.ok(q('.chart-card svg'));
  assert.match(q('.attention-card').textContent, /Yuklanmoqda/);
  release();
  await tick(15);
  assert.equal(qa('.attention').length, 3);
});

test('needs-attention lists problematic orders and sets the badge', async () => {
  stubFetch(dashRoutes());
  await mount('dash');
  assert.equal(qa('.attention').length, 3);
  assert.match(q('.attention').textContent, /GH-000001/);
  assert.match(q('.attention').textContent, /Sabab 1/);
  assert.equal(getBadge('orders'), 3);
});

test('needs-attention empty state', async () => {
  stubFetch(dashRoutes({ '/api/v1/admin/orders/problematic': { counts: { total_problematic: 0 }, orders: [] } }));
  const o = await mount('dash');
  assert.equal(qa('.attention').length, 0);
  assert.match(o.textContent, /Muammoli buyurtmalar yo'q/);
});

test('dash without ORDERS_READ does not call the problematic endpoint', async () => {
  adminState.admin = { id: 2, permissions: ['ANALYTICS_READ'] };
  stubFetch(dashRoutes());
  const o = await mount('dash');
  assert.equal(calls(/problematic/).length, 0);
  assert.equal(o.textContent.includes("E'tibor talab qiladi"), false);
});

test('dash: a failing problematic request does not break the page', async () => {
  stubFetch(dashRoutes({ '/api/v1/admin/orders/problematic': () => jsonRes(500, { detail: 'boom' }) }));
  const o = await mount('dash');
  assert.equal(qa('.kpi').length, 4);
  assert.match(o.textContent, /boom/);
});

test('dash stats failure rejects so the router shows retry', async () => {
  stubFetch({ '/api/admin/stats': () => jsonRes(500, { detail: 'stats down' }) });
  await assert.rejects(() => getView('dash')({ id: 'dash' }), /stats down/);
});

test('retry needs confirmation, posts the legacy body once, then refreshes', async () => {
  let n = 0;
  stubFetch(dashRoutes({
    'POST /api/v1/admin/orders/1/retry-fulfillment': () => { n++; return { success: true, result: {} }; },
  }));
  await mount('dash');
  const retry = qa('.attention')[0].querySelector('button');
  assert.equal(retry.textContent.trim(), 'Qayta yuborish');
  fire(retry);
  assert.ok(q('[role="dialog"]'));
  assert.equal(calls(/POST/).length, 0);
  await confirmYes('Yuborish');
  assert.equal(n, 1);
  const post = calls(/^POST/)[0];
  assert.match(post.body.reason, /\S{5,}/);
  assert.equal(post.headers['X-Telegram-Init-Data'], 'query_id=1');
  assert.equal(calls(/GET .*problematic/).length, 2);
});

test('cancelling the retry confirmation sends nothing', async () => {
  stubFetch(dashRoutes());
  await mount('dash');
  fire(qa('.attention')[0].querySelector('button'));
  click('Bekor qilish');
  await tick();
  assert.equal(calls(/^POST/).length, 0);
});

test('retry is disabled while the request is in flight (no double submit)', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  let n = 0;
  stubFetch(dashRoutes({
    'POST /api/v1/admin/orders/1/retry-fulfillment': async () => { n++; await gate; return { success: true }; },
  }));
  await mount('dash');
  const retry = qa('.attention')[0].querySelector('button');
  fire(retry);
  await confirmYes('Yuborish');
  assert.equal(retry.hasAttribute('disabled'), true);
  fire(retry);
  fire(retry);
  assert.ok(!q('[role="dialog"]'));
  release();
  await tick();
  assert.equal(n, 1);
});

test('manual fulfil goes through a danger confirm and posts a reason', async () => {
  stubFetch(dashRoutes({ 'POST /api/v1/admin/orders/1/manual-fulfill': { success: true } }));
  await mount('dash');
  fire(btn("Qo'lda bajarildi"));
  assert.ok(q('[role="dialog"] .btn-danger'));
  await confirmYes('Bajarildi deb belgilash');
  const post = calls(/^POST/)[0];
  assert.match(post.url, /orders\/\d+\/manual-fulfill/);
  assert.ok(post.body.reason.length >= 5);
});

test('retry buttons are hidden without ORDERS_UPDATE', async () => {
  adminState.admin = { id: 2, permissions: ['ANALYTICS_READ', 'ORDERS_READ'] };
  stubFetch(dashRoutes());
  await mount('dash');
  assert.equal(qa('.attention').length, 3);
  assert.deepEqual(qa('.attention button').map((b) => b.textContent.trim()), ['Tarix', 'Tarix', 'Tarix']);
});

// ---- users ----
const USERS = [
  { id: 1, first_name: '<img src=x onerror=alert(1)>', username: '@evil', role: 'user', balance: 15000, orders_count: 2, total_spent: 90000, referrals_count: 1, created_at: '01 Nov 2026' },
  { id: 2, first_name: 'Ali', username: '2', role: 'admin', balance: 0, orders_count: 0, total_spent: 0, referrals_count: 0, created_at: '02 Nov 2026' },
];

test('user name with HTML is rendered as text', async () => {
  stubFetch({ '/api/admin/users': USERS });
  const o = await mount('users');
  assert.equal(o.querySelector('img'), null);
  assert.match(o.textContent, /<img src=x onerror=alert\(1\)>/);
  assert.match(o.textContent, /15 000 so'm/);
  assert.match(o.textContent, /90 000 so'm/);
});

test('users search is debounced and sent as ?search=', async () => {
  stubFetch({ '/api/admin/users': USERS });
  await mount('users');
  const input = q('input[type="search"]');
  input.value = 'al i';
  fire(input, 'input');
  input.value = 'ali';
  fire(input, 'input');
  assert.equal(calls(/users/).length, 1);
  await tick(450);
  assert.equal(calls(/users/).length, 2);
  assert.match(lastUrl(), /\/api\/admin\/users\?.*search=ali/);
  assert.match(lastUrl(), /offset=0/);
});

test('users paging uses limit+1 to detect a next page', async () => {
  const many = Array.from({ length: 21 }, (_, i) => ({ ...USERS[1], id: i + 1, first_name: `U${i}` }));
  stubFetch({ '/api/admin/users': many });
  const o = await mount('users');
  assert.match(fetchLog[0].url, /limit=21/);
  assert.equal(qa('.users tbody tr').length, 20);
  click('Keyingi');
  await tick();
  assert.match(lastUrl(), /offset=20/);
  assert.ok(btn('Oldingi'));
  assert.ok(o);
});

test('users empty state', async () => {
  stubFetch({ '/api/admin/users': [] });
  const o = await mount('users');
  assert.match(o.textContent, /Foydalanuvchi topilmadi/);
});

// ---- orders ----
const ORDERS = [
  { id: 5, order_code: 'GH-000005', user_id: 1, username: '<b>x</b>', product_type: 'stars', item_title: 'Stars 100', amount: 100, total_price: 25000, cost_price: 20000, status: 'pending', recipient_username: 'bob', fulfillment_status: 'pending', fragment_payload: 'https://app.tonkeeper.com/transfer/abc', fragment_tx_hash: null, fulfillment_error: null, created_at: '15 Nov, 10:00' },
  { id: 6, order_code: 'GH-000006', user_id: 2, username: '@ali', product_type: 'gift', item_title: 'Gift', amount: 1, total_price: 5000, cost_price: 4000, status: 'completed', recipient_username: null, fulfillment_status: 'fulfilled', fragment_payload: 'ton://transfer/x', fragment_tx_hash: 'HASH/1', fulfillment_error: null, created_at: '15 Nov, 11:00' },
];

test('orders render as text with legacy columns and safe links', async () => {
  stubFetch({ '/api/admin/orders': ORDERS });
  const o = await mount('orders');
  assert.equal(qa('.orders td b').some((b) => b.textContent === 'x'), false);
  assert.match(o.textContent, /<b>x<\/b>/);
  assert.match(o.textContent, /25 000 so'm/);
  const hrefs = qa('.orders a').map((a) => a.getAttribute('href'));
  assert.ok(hrefs.includes('https://app.tonkeeper.com/transfer/abc'));
  assert.ok(hrefs.includes('https://tonscan.org/tx/HASH%2F1'));
  assert.equal(hrefs.some((h) => h && h.startsWith('ton:')), false);
});

test('orders filters and search build the legacy query', async () => {
  stubFetch({ '/api/admin/orders': ORDERS });
  await mount('orders');
  click('Bajarildi');
  await tick();
  assert.match(lastUrl(), /status=done/);
  click('Stars');
  await tick();
  assert.match(lastUrl(), /product_type=stars/);
  assert.match(lastUrl(), /status=done/);
  click('Hammasi');
  assert.equal(/status=/.test(lastUrl()), false);
  const input = q('input[type="search"]');
  input.value = 'GH-5';
  fire(input, 'input');
  await tick(450);
  assert.match(lastUrl(), /search=GH-5/);
});

test('orders export fetches with the auth header and downloads a blob', async () => {
  stubFetch({
    '/api/admin/orders': ORDERS,
    '/api/admin/export/orders.csv': () => new Response('ID,Kod\n1,GH-1', { status: 200, headers: { 'Content-Type': 'text/csv' } }),
  });
  await mount('orders');
  const created = [];
  const origCreate = document.createElement.bind(document);
  document.createElement = (tag, ...rest) => {
    const el = origCreate(tag, ...rest);
    if (String(tag).toLowerCase() === 'a') {
      created.push(el);
      el.click = () => { el.__clicked = true; };
    }
    return el;
  };
  const origObj = URL.createObjectURL;
  const origRev = URL.revokeObjectURL;
  const revoked = [];
  const timers = [];
  const origSet = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms, ...a) => {
    if (ms >= 30000) { timers.push([fn, ms]); return 0; }
    return origSet(fn, ms, ...a);
  };
  URL.createObjectURL = () => 'blob:test-1';
  URL.revokeObjectURL = (u) => revoked.push(u);
  try {
    click('Eksport');
    await tick(30);
    assert.deepEqual(revoked, [], 'not revoked immediately');
    for (const [fn] of timers) fn();
    assert.deepEqual(revoked, ['blob:test-1']);
    assert.ok(timers.some(([, ms]) => ms >= 30000), 'revoke is delayed ~30 s');
  } finally {
    document.createElement = origCreate;
    globalThis.setTimeout = origSet;
    URL.createObjectURL = origObj;
    URL.revokeObjectURL = origRev;
  }
  const req = calls(/export\/orders\.csv/)[0];
  assert.ok(req);
  assert.equal(req.headers['X-Telegram-Init-Data'], 'query_id=1');
  const a = created.find((x) => x.__clicked);
  assert.ok(a, 'anchor clicked');
  assert.equal(a.getAttribute('href'), 'blob:test-1');
  assert.equal(a.getAttribute('download'), 'gifthub_orders.csv');
});

test('cancel order: danger confirm, then POST status cancel, no double submit', async () => {
  let n = 0;
  stubFetch({
    '/api/admin/orders': ORDERS,
    'POST /api/admin/orders/5/status': (init) => { n++; return { success: true, status: 'cancelled' }; },
  });
  await mount('orders');
  const cancel = qa('.orders button').find((b) => b.textContent.trim() === 'Qaytarish');
  assert.ok(cancel, 'cancel button');
  fire(cancel);
  assert.ok(q('[role="dialog"] .btn-danger'));
  await confirmYes('Bekor qilish va qaytarish');
  fire(cancel);
  await tick();
  assert.equal(n, 1);
  assert.deepEqual(calls(/^POST/)[0].body, { status: 'cancel' });
});

test('mark fulfilled and fragment actions hit the legacy endpoints', async () => {
  stubFetch({
    '/api/admin/orders': ORDERS,
    'POST /api/admin/orders/5/mark-fulfilled': { success: true },
    'POST /api/admin/orders/5/fulfill-fragment': { success: true, fulfilled: true },
  });
  await mount('orders');
  fire(qa('.orders button').find((b) => b.textContent.trim() === 'Yetkazildi'));
  await confirmYes('Belgilash');
  fire(qa('.orders button').find((b) => b.textContent.trim() === 'Fragment'));
  await confirmYes('Yetkazish');
  assert.deepEqual(calls(/^POST/).map((c) => c.url), [
    '/api/admin/orders/5/mark-fulfilled', '/api/admin/orders/5/fulfill-fragment',
  ]);
});

test('order actions are hidden without ORDERS_UPDATE', async () => {
  adminState.admin = { id: 2, permissions: ['ORDERS_READ'] };
  stubFetch({ '/api/admin/orders': ORDERS });
  await mount('orders');
  assert.deepEqual(qa('.orders td button').map((b) => b.textContent.trim()), ['Tarix', 'Tarix']);
});

// ---- payments ----
const PAY = {
  click_active: true, payme_active: false, card_active: true, card_number: '8600 1111 2222 3333',
  card_holder: 'ANVAR S.', bank_name: 'TBC Bank', autopaycard_active: true, autopaycard_last4: '6412',
  autopaycard_email: 'a@b.c', autopaycard_webhook_url: 'https://x',
};
const CARDS = [
  { id: 3, card_number: '8600 0000 1111 2222', card_holder: '<b>EGA</b>', bank_name: 'Bank', card_type: 'UZCARD', is_active: true },
];
const payRoutes = (extra = {}) => ({ '/api/admin/payments': PAY, '/api/admin/cards': CARDS, ...extra });

test('payments render methods and cards as text', async () => {
  stubFetch(payRoutes());
  const o = await mount('payments');
  assert.equal(qa('.bank-card b').some((b) => b.textContent === 'EGA'), false);
  assert.match(o.textContent, /<b>EGA<\/b>/);
  assert.match(o.textContent, /Click/);
  assert.match(o.textContent, /8600 0000 1111 2222/);
});

test('toggling a method saves the full settings so other fields are not reset', async () => {
  stubFetch(payRoutes({ 'POST /api/admin/payments': { success: true } }));
  await mount('payments');
  const sw = q('[role="switch"][aria-label="Payme"]');
  assert.equal(sw.getAttribute('aria-checked'), 'false');
  fire(sw);
  assert.equal(q('[role="dialog"] .btn-danger'), null, 'enabling is a plain confirm');
  await confirmYes('Yoqish');
  const post = calls(/^POST/)[0];
  assert.equal(post.body.payme_active, true);
  assert.equal(post.body.click_active, true);
  assert.equal(post.body.card_number, '8600 1111 2222 3333');
  assert.equal(post.body.autopaycard_active, true);
  assert.equal('autopaycard_api_key' in post.body, false);
  assert.equal(sw.getAttribute('aria-checked'), 'true');
});

test('failed toggle rolls the switch back', async () => {
  stubFetch(payRoutes({ 'POST /api/admin/payments': () => jsonRes(500, { detail: 'x' }) }));
  await mount('payments');
  const sw = q('[role="switch"][aria-label="Click"]');
  fire(sw);
  await confirmYes("Ha, o'chirish");
  assert.equal(calls(/^POST/).length, 1);
  assert.equal(sw.getAttribute('aria-checked'), 'true');
});

test('deleting a card needs a danger confirm', async () => {
  stubFetch(payRoutes({ 'DELETE /api/admin/cards/3': { success: true } }));
  await mount('payments');
  fire(qa('button').find((b) => b.getAttribute('aria-label') === "Kartani o'chirish"));
  assert.ok(q('[role="dialog"] .btn-danger'));
  assert.equal(calls(/^DELETE/).length, 0);
  await confirmYes("Ha, o'chirish");
  assert.equal(calls(/^DELETE/).length, 1);
});

test('adding a card validates, then posts the legacy body', async () => {
  stubFetch(payRoutes({ 'POST /api/admin/cards': { success: true, id: 9 } }));
  await mount('payments');
  click("Karta qo'shish");
  const form = q('form.card-form');
  const set = (name, v) => { const i = form.querySelector(`[name="${name}"]`); i.value = v; fire(i, 'input'); };
  set('card_number', '8600 12');
  set('card_holder', 'ali v');
  set('bank_name', 'Xalq');
  fire(form, 'submit');
  await tick();
  assert.equal(calls(/^POST/).length, 0);
  assert.match(form.textContent, /16/);
  set('card_number', '8600 1234 5678 9012');
  fire(form, 'submit');
  await tick();
  assert.equal(calls(/^POST/).length, 0, 'save asks for confirmation first');
  await confirmYes('Ha, saqlash');
  const post = calls(/^POST/)[0];
  assert.equal(post.url, '/api/admin/cards');
  assert.deepEqual(post.body, {
    card_number: '8600 1234 5678 9012', card_holder: 'ALI V', bank_name: 'Xalq', card_type: 'UZCARD', is_active: true,
  });
});

test('payment write controls are hidden without SETTINGS_UPDATE', async () => {
  adminState.admin = { id: 2, permissions: ['PAYMENTS_READ'] };
  stubFetch(payRoutes());
  const o = await mount('payments');
  assert.equal(qa('[role="switch"]').every((s) => s.hasAttribute('disabled')), true);
  assert.equal(btn("Karta qo'shish"), undefined);
  assert.ok(o);
});


// ---- fix round 1 ----
test('attention rows show payment method, order status and fulfillment status', async () => {
  const o = { ...PROBLEMS.orders[0], payment_method: 'card', status: 'processing', fulfillment_status: 'failed' };
  stubFetch(dashRoutes({ '/api/v1/admin/orders/problematic': { ...PROBLEMS, orders: [o] } }));
  await mount('dash');
  const t = q('.attention').textContent;
  assert.match(t, /To'lov: card/);
  assert.match(t, /Jarayonda/);
  assert.match(t, /Yetkazish: failed/);
});

test('retry asks for a reason, blocks an empty one and sends the typed text', async () => {
  stubFetch(dashRoutes({ 'POST /api/v1/admin/orders/1/retry-fulfillment': { success: true } }));
  await mount('dash');
  fire(qa('.attention')[0].querySelector('button'));
  const input = q('[role="dialog"] input[name="reason"]');
  assert.ok(input);
  input.value = '   ';
  click('Yuborish');
  assert.ok(q('[role="dialog"]'), 'dialog stays open');
  assert.match(q('.confirm-error').textContent, /Sabab/);
  assert.equal(calls(/^POST/).length, 0);
  input.value = 'Fragment qayta urinish';
  await confirmYes('Yuborish');
  assert.equal(calls(/^POST/)[0].body.reason, 'Fragment qayta urinish');
});

test('manual fulfil blocks a reason shorter than the backend minimum', async () => {
  stubFetch(dashRoutes({ 'POST /api/v1/admin/orders/1/manual-fulfill': { success: true } }));
  await mount('dash');
  fire(btn("Qo'lda bajarildi"));
  const input = q('[role="dialog"] input[name="reason"]');
  input.value = 'abc';
  click('Bajarildi deb belgilash');
  assert.match(q('.confirm-error').textContent, /kamida 5/);
  assert.equal(calls(/^POST/).length, 0);
  input.value = "Qo'lda yuborildi";
  await confirmYes('Bajarildi deb belgilash');
  assert.equal(calls(/^POST/)[0].body.reason, "Qo'lda yuborildi");
});

test('confirmDialog keeps its boolean contract and confirmWithReason returns the value', async () => {
  const { confirmDialog, confirmWithReason } = await import('./confirm.js');
  const a = confirmDialog({ title: 'A' });
  click('Tasdiqlash');
  assert.equal(await a, true);
  const b = confirmWithReason({ title: 'B', input: { label: 'Sabab', required: true, defaultValue: 'x1' } });
  click('Tasdiqlash');
  assert.deepEqual(await b, { confirmed: true, value: 'x1' });
  const c = confirmWithReason({ title: 'C', input: { label: 'Sabab' } });
  click('Bekor qilish');
  assert.equal((await c).confirmed, false);
});

test('a second confirm dialog cannot open while one is open (resolves false)', async () => {
  const { confirmDialog } = await import('./confirm.js');
  const first = confirmDialog({ title: 'first' });
  assert.equal(await confirmDialog({ title: 'second' }), false);
  assert.equal(qa('[role="dialog"]').length, 1);
  assert.match(q('[role="dialog"]').textContent, /first/);
  click('Bekor qilish');
  assert.equal(await first, false);
});

test('one lock per order: manual cannot start while retry on the same order is pending', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch(dashRoutes({
    'POST /api/v1/admin/orders/1/retry-fulfillment': async () => { await gate; return { success: true }; },
    'POST /api/v1/admin/orders/1/manual-fulfill': { success: true },
  }));
  await mount('dash');
  const row = qa('.attention')[0];
  const [retry, manual] = row.querySelectorAll('button');
  fire(retry);
  await confirmYes('Yuborish');
  fire(manual);
  assert.ok(!q('[role="dialog"]'), 'no dialog for the same order');
  release();
  await tick();
  assert.equal(calls(/manual-fulfill/).length, 0);
});

test('dialogs are serialised across different orders too', async () => {
  stubFetch(dashRoutes());
  await mount('dash');
  fire(qa('.attention')[0].querySelector('button'));
  fire(qa('.attention')[1].querySelector('button'));
  assert.equal(qa('[role="dialog"]').length, 1);
});

test('"Barchasini" link opens the full problem list with category tabs and counts', async () => {
  const many = Array.from({ length: 12 }, (_, i) => ({ ...PROBLEMS.orders[0], id: 100 + i, order_code: `GH-1${i}` }));
  const counts = { total_problematic: 12, paid_not_fulfilled: 5, stuck_processing: 3, payment_mismatch: 1, failed_fulfillment: 2, pending_refund: 1 };
  stubFetch(dashRoutes({
    '/api/v1/admin/orders/problematic': (init, url) => (/category=stuck_processing/.test(url)
      ? { counts, orders: many.slice(0, 2) } : { counts, orders: many }),
  }));
  await mount('dash');
  assert.equal(qa('.attention').length, 5);
  const more = q('a.link-more');
  assert.equal(more.getAttribute('href'), '#/orders/problems');
  document.body.textContent = '';
  const panel = await getView('orders')({ id: 'orders', sub: 'problems' });
  document.body.appendChild(panel);
  assert.equal(qa('.attention').length, 10);
  for (const label of ['Hammasi (12)', "To'langan, yetkazilmagan (5)", 'Qotib qolgan (3)', "To'lov mos emas (1)", 'Yetkazish xatosi (2)', 'Qaytarish kutilmoqda (1)']) {
    assert.ok(btn(label), label);
  }
  click('Keyingi');
  assert.equal(qa('.attention').length, 2);
  click('Qotib qolgan (3)');
  await tick();
  assert.match(lastUrl(), /problematic\?category=stuck_processing/);
  assert.equal(qa('.attention').length, 2);
  assert.equal(getBadge('orders'), 12);
});

test('orders view links to the problem list', async () => {
  stubFetch({ '/api/admin/orders': ORDERS });
  await mount('orders');
  assert.ok(qa('a').some((a) => a.getAttribute('href') === '#/orders/problems'));
});

const TIMELINE = {
  success: true, order_code: 'GH-000001',
  timeline: [
    { id: 1, from_status: null, to_status: 'created', actor: 'SYSTEM', note: null, created_at: '2026-11-15T10:00:00Z' },
    { id: 2, from_status: 'created', to_status: 'paid', actor: '<img src=x onerror=alert(1)>', note: '<b>izoh</b>', created_at: '2026-11-15T10:05:00Z' },
  ],
};

test('timeline modal opens from an attention row and renders entries as text', async () => {
  stubFetch(dashRoutes({ '/api/v1/orders/GH-000001/timeline': TIMELINE }));
  await mount('dash');
  fire(qa('.attention')[0].querySelectorAll('button')[2]);
  await tick();
  const dlg = q('[role="dialog"]');
  assert.match(dlg.textContent, /Buyurtma kodi: GH-000001/);
  assert.equal(qa('.timeline-item').length, 2);
  assert.match(dlg.textContent, /Boshlang'ich holat: created/);
  assert.match(dlg.textContent, /created → paid/);
  assert.equal(dlg.querySelector('img'), null);
  assert.equal(dlg.querySelector('.timeline-item b + b'), null);
  assert.match(dlg.textContent, /<img src=x onerror=alert\(1\)>/);
  assert.match(dlg.textContent, /<b>izoh<\/b>/);
  assert.equal(fetchLog.at(-1).headers['X-Telegram-Init-Data'], 'query_id=1');
  click('Yopish');
  assert.equal(q('[role="dialog"]'), null);
});

test('timeline opens from the orders view and shows empty and error states', async () => {
  stubFetch({ '/api/admin/orders': ORDERS, '/api/v1/orders/GH-000005/timeline': { timeline: [] } });
  await mount('orders');
  fire(qa('.orders td button').find((b) => b.textContent.trim() === 'Tarix'));
  await tick();
  assert.match(q('[role="dialog"]').textContent, /Tarix topilmadi/);
  click('Yopish');
  stubFetch({ '/api/admin/orders': ORDERS, '/api/v1/orders/GH-000005/timeline': () => jsonRes(404, { detail: 'Buyurtma topilmadi.' }) });
  fire(qa('.orders td button').find((b) => b.textContent.trim() === 'Tarix'));
  await tick();
  assert.match(q('[role="dialog"]').textContent, /Buyurtma topilmadi/);
});

test('same-order lock is shared between the orders table actions', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({
    '/api/admin/orders': ORDERS,
    'POST /api/admin/orders/5/mark-fulfilled': async () => { await gate; return { success: true }; },
    'POST /api/admin/orders/5/status': { success: true },
  });
  await mount('orders');
  fire(qa('.orders button').find((b) => b.textContent.trim() === 'Yetkazildi'));
  await confirmYes('Belgilash');
  fire(qa('.orders button').find((b) => b.textContent.trim() === 'Qaytarish'));
  assert.ok(!q('[role="dialog"]'));
  release();
  await tick();
  assert.equal(calls(/\/status/).length, 0);
});

test('formatDate formats ISO and passes server display strings through', async () => {
  const { formatDate } = await import('./views/ui.js');
  assert.match(formatDate('2026-11-15T10:05:00Z'), /^\d\d\.\d\d \d\d:\d\d$/);
  assert.equal(formatDate('15 Nov, 10:00'), '15 Nov, 10:00');
  assert.equal(formatDate(null), '');
});

test('deactivating a card is a danger confirm with the "nofaol" toast; activating is plain', async () => {
  const two = [CARDS[0], { ...CARDS[0], id: 4, bank_name: 'Boshqa', is_active: false }];
  stubFetch(payRoutes({
    '/api/admin/cards': two,
    'PUT /api/admin/cards/3': { success: true },
    'PUT /api/admin/cards/4': { success: true },
  }));
  await mount('payments');
  fire(q('[role="switch"][aria-label="Bank kartasi faol"]'));
  assert.ok(q('[role="dialog"] .btn-danger'));
  await confirmYes('Nofaol qilish');
  assert.deepEqual(calls(/^PUT/)[0].body, { is_active: false });
  assert.equal(q('#toast').textContent, 'Karta nofaol qilindi');
  fire(q('[role="switch"][aria-label="Boshqa kartasi faol"]'));
  assert.equal(q('[role="dialog"] .btn-danger'), null);
  await confirmYes('Faol qilish');
  assert.deepEqual(calls(/^PUT/)[1].body, { is_active: true });
});

test('cancelling a payment method confirmation sends nothing and keeps the switch', async () => {
  stubFetch(payRoutes());
  await mount('payments');
  const sw = q('[role="switch"][aria-label="Click"]');
  fire(sw);
  click('Bekor qilish');
  await tick();
  assert.equal(calls(/^POST/).length, 0);
  assert.equal(sw.getAttribute('aria-checked'), 'true');
});

// ---- guards ----
test('view modules never use unsafe DOM APIs or the versioned entry', () => {
  const dir = new URL('./views/', import.meta.url);
  const files = [...readdirSync(dir).filter((f) => f.endsWith('.js')).map((f) => new URL(f, dir)), new URL('./chart.js', import.meta.url)];
  for (const f of files) {
    const src = readFileSync(f, 'utf8');
    assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML/, f.pathname);
    assert.doesNotMatch(src, /from\s+['"][^'"]*\/admin\.js['"]/, f.pathname);
  }
});
