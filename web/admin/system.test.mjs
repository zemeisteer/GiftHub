import { test, before, after, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let getView, adminState, tg, setSelect;
let fetchLog;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const ALL = [
  'USERS_READ', 'ORDERS_READ', 'ORDERS_UPDATE', 'ORDERS_REFUND', 'PRICING_READ', 'PRICING_UPDATE',
  'PAYMENTS_READ', 'BROADCAST_CREATE', 'BROADCAST_SEND', 'ANALYTICS_READ', 'ADMINS_READ', 'ADMINS_MANAGE',
  'SETTINGS_READ', 'SETTINGS_UPDATE',
];

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
  for (const v of ['broadcast', 'channels', 'gate', 'fragment', 'health', 'admins']) await import(`./views/${v}.js`);
  ({ tg } = await import('../shared/tg.js'));
  ({ setSelect } = await import('./forms.js'));
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

// Views started polling with real timers in the plain tests: detach and let them dispose.
after(() => {
  document.body.textContent = '';
  document.dispatchEvent(new Event('visibilitychange'));
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
const dialogText = () => (q('[role="dialog"]') || { textContent: '' }).textContent;
async function confirmYes() {
  assert.ok(q('[role="dialog"]'), 'confirm dialog expected');
  fire(q('.confirm-actions .btn:last-child'));
  await tick();
}
const hasText = (s) => document.body.textContent.includes(s);
async function mount(id) {
  const node = await getView(id)({ id });
  const outlet = document.createElement('main');
  outlet.appendChild(node);
  document.body.appendChild(outlet);
  await tick(15);
  return outlet;
}

// ---------------- broadcast ----------------
const DRAFT = { has_draft: true, draft: { id: 7, mode: 'text', text: 'Salom', created_at: '15 Nov, 10:00' } };

test('broadcast draft restored into the text field on open', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': DRAFT });
  await mount('broadcast');
  assert.equal(input('text').value, 'Salom');
  assert.ok(hasText('15 Nov, 10:00'));
});

test('broadcast without a draft starts empty and still works', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false } });
  await mount('broadcast');
  assert.equal(input('text').value, '');
});

test('broadcast send needs a danger confirm naming the audience, then sends once', async () => {
  stubFetch({
    '/api/admin/broadcast/latest-draft': DRAFT,
    'POST /api/admin/broadcast': { success: true, recipients_count: 42, message: 'Broadcast 42 ta foydalanuvchiga yuborilmoqda...' },
  });
  await mount('broadcast');
  click('Yuborish');
  await tick();
  assert.match(dialogText(), /Barcha foydalanuvchilarga/);
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/POST/).length, 0);
  await confirmYes();
  const posts = calls(/POST/);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.segment, 'all');
  assert.equal(posts[0].body.text, 'Salom');
  assert.equal(posts[0].body.draft_id, 7);
  assert.ok(hasText('Qabul qiluvchilar soni: 42 ta'));
});

test('broadcast segment and buttons go into the body; bad button URL is refused', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false }, 'POST /api/admin/broadcast': { recipients_count: 1 } });
  await mount('broadcast');
  input('text').value = 'Aksiya';
  click('Hali xarid qilmaganlar');
  click("Tugma qo'shish");
  input('btn_text').value = 'Ochish';
  input('btn_url').value = 'javascript-alert';
  click('Yuborish');
  await tick();
  assert.ok(hasText('Tugma havolasi'));
  assert.equal(q('[role="dialog"]'), null);
  input('btn_url').value = 'https://t.me/gifthubuzbot/app';
  click('Yuborish');
  await tick();
  assert.match(dialogText(), /xarid qilmagan/);
  await confirmYes();
  const b = lastBody();
  assert.equal(b.segment, 'non_buyers');
  assert.deepEqual(b.buttons, [{ text: 'Ochish', url: 'https://t.me/gifthubuzbot/app' }]);
  assert.equal(b.draft_id, undefined);
});

test('broadcast refuses an empty text and cancelling the confirm sends nothing', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false } });
  await mount('broadcast');
  click('Yuborish');
  await tick();
  assert.ok(hasText('Xabar matnini kiriting'));
  input('text').value = 'x';
  click('Yuborish');
  await tick();
  fire(q('.confirm-actions .btn-secondary'));
  await tick();
  assert.equal(calls(/POST/).length, 0);
});

test('broadcast double click on send opens one confirm and one request', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': DRAFT, 'POST /api/admin/broadcast': { recipients_count: 3 } });
  await mount('broadcast');
  click('Yuborish');
  click('Yuborish');
  await tick();
  assert.equal(qa('[role="dialog"]').length, 1);
  await confirmYes();
  click('Yuborish');
  await tick();
  fire(q('.confirm-actions .btn-secondary'));
  assert.equal(calls(/POST/).length, 1);
});

test('broadcast post-link mode sends link and forward flag', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false }, 'POST /api/admin/broadcast': { recipients_count: 5 } });
  await mount('broadcast');
  click('Telegram postidan');
  input('post_link').value = 'https://t.me/kanal/12';
  input('forward_mode').checked = true;
  click('Yuborish');
  await tick();
  await confirmYes();
  const b = lastBody();
  assert.equal(b.mode, 'post_link');
  assert.equal(b.post_link, 'https://t.me/kanal/12');
  assert.equal(b.forward_mode, true);
});

test('broadcast preview shows markup as text, never as elements', async () => {
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false } });
  await mount('broadcast');
  input('text').value = '<img src=x onerror=alert(1)><b>qalin</b>';
  fire(input('text'), 'input');
  assert.equal(qa('.preview-text img').length, 0);
  assert.equal(qa('.preview-text b').length, 0);
  assert.ok(q('.preview-text').textContent.includes('<b>qalin</b>'));
});

test('broadcast send is disabled without BROADCAST_SEND', async () => {
  adminState.admin = { id: 2, role: 'marketing', permissions: ['BROADCAST_CREATE'] };
  stubFetch({ '/api/admin/broadcast/latest-draft': { has_draft: false } });
  await mount('broadcast');
  assert.equal(btn('Yuborish').hasAttribute('disabled'), true);
});

// ---------------- channels / gate ----------------
const CHANNELS = [
  { id: 1, title: 'GiftHub News', username_or_link: '@gifthub', req_type: 'ordinary', is_active: true, is_detected: false },
  { id: 2, title: 'Eski', username_or_link: '@old', req_type: 'group', is_active: false, is_detected: false },
  { id: 3, title: '<b>Yangi</b>', username_or_link: '@new', req_type: 'ordinary', is_active: false, is_detected: true },
];

test('channels lists active, detected and escapes titles', async () => {
  stubFetch({ '/api/admin/channels': CHANNELS, '/api/bot-info': { username: 'gifthubuzbot' } });
  await mount('channels');
  assert.ok(hasText('GiftHub News'));
  assert.ok(hasText('Aniqlangan kanallar'));
  assert.ok(hasText('<b>Yangi</b>'));
  assert.equal(qa('b').filter((b) => b.textContent === 'Yangi').length, 0);
});

test('channels add posts the body and auto-detects the type from the link', async () => {
  stubFetch({ '/api/admin/channels': [], 'POST /api/admin/channels': { success: true, title: 'X' }, '/api/bot-info': {} });
  await mount('channels');
  const link = input('username_or_link');
  link.value = 'https://t.me/+abc123';
  fire(link, 'input');
  assert.ok(hasText('Avto: Zayavka'));
  fire(q('form'), 'submit');
  await tick();
  assert.deepEqual(lastBody(), { username_or_link: 'https://t.me/+abc123', title: null, req_type: 'join_request' });
});

test('channels delete is a danger confirm', async () => {
  stubFetch({ '/api/admin/channels': CHANNELS, 'DELETE /api/admin/channels/1': { success: true }, '/api/bot-info': {} });
  await mount('channels');
  click("O'chirish");
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/DELETE/).length, 0);
  await confirmYes();
  assert.equal(calls(/DELETE \/api\/admin\/channels\/1$/).length, 1);
});

test('channels detected: Tayyor confirms with the chosen type', async () => {
  stubFetch({ '/api/admin/channels': CHANNELS, 'POST /api/admin/channels/3/confirm': { success: true }, '/api/bot-info': {} });
  await mount('channels');
  click('Tayyor');
  await tick();
  assert.deepEqual(lastBody(), { req_type: 'ordinary' });
});

test('channels type change posts req_type', async () => {
  stubFetch({ '/api/admin/channels': [CHANNELS[0]], 'POST /api/admin/channels/1/type': { success: true }, '/api/bot-info': {} });
  await mount('channels');
  const sel = q('li select');
  setSelect(sel, 'group');
  fire(sel, 'change');
  await tick();
  assert.deepEqual(lastBody(), { req_type: 'group' });
});

test('gate shows only enforcing channels and confirms before turning one off', async () => {
  stubFetch({ '/api/admin/channels': CHANNELS, 'POST /api/admin/channels/1/toggle': { success: true, is_active: false } });
  await mount('gate');
  assert.ok(hasText('GiftHub News'));
  assert.equal(hasText('Eski'), false);
  assert.equal(hasText('<b>Yangi</b>'), false);
  assert.ok(hasText('Yoqilgan'));
  assert.equal(btn("O'chirish"), undefined);
  fire(q('[role="switch"]'));
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/toggle/).length, 0);
  await confirmYes();
  assert.equal(calls(/toggle/).length, 1);
});

test('gate with no active channels reports the gate is off', async () => {
  stubFetch({ '/api/admin/channels': [CHANNELS[1]] });
  await mount('gate');
  assert.ok(hasText("O'chiq"));
});

// ---------------- channels auto-refresh ----------------
const setVisibility = (state) => {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  fire(document, 'visibilitychange');
};
// Detach the view and let it dispose its timer while the fake clock is still the active one.
const leave = (outlet) => { if (outlet) outlet.remove(); fire(document, 'visibilitychange'); };
const listCalls = () => calls(/GET \/api\/admin\/channels$/).length;

test('channels polls every 5 s and shows newly detected channels', async () => {
  mock.timers.enable({ apis: ['setInterval'] });
  let outlet = null;
  try {
    let list = [CHANNELS[0]];
    stubFetch({ '/api/admin/channels': () => list, '/api/bot-info': {} });
    outlet = await mount('channels');
    assert.equal(listCalls(), 1);
    assert.equal(hasText('Aniqlangan kanallar'), false);
    list = CHANNELS;
    mock.timers.tick(4000);
    await tick();
    assert.equal(listCalls(), 1);
    mock.timers.tick(1000);
    await tick();
    assert.equal(listCalls(), 2);
    assert.ok(hasText('Aniqlangan kanallar'));
  } finally { leave(outlet); mock.timers.reset(); }
});

test('channels poll never overlaps a request in flight', async () => {
  mock.timers.enable({ apis: ['setInterval'] });
  let outlet = null;
  try {
    let release;
    let slow = false;
    stubFetch({
      '/api/admin/channels': () => (slow ? new Promise((r) => { release = () => r([]); }) : [CHANNELS[0]]),
      '/api/bot-info': {},
    });
    outlet = await mount('channels');
    slow = true;
    mock.timers.tick(5000);
    await tick();
    mock.timers.tick(5000);
    mock.timers.tick(5000);
    await tick();
    assert.equal(listCalls(), 2);
    release();
    await tick();
  } finally { leave(outlet); mock.timers.reset(); }
});

test('channels poll stops once the view leaves the page', async () => {
  mock.timers.enable({ apis: ['setInterval'] });
  let outlet = null;
  try {
    stubFetch({ '/api/admin/channels': [CHANNELS[0]], '/api/bot-info': {} });
    outlet = await mount('channels');
    outlet.remove();
    mock.timers.tick(5000);
    await tick();
    mock.timers.tick(5000);
    await tick();
    assert.equal(listCalls(), 1);
  } finally { leave(outlet); mock.timers.reset(); }
});

test('channels poll pauses while the page is hidden and resumes with a refresh', async () => {
  mock.timers.enable({ apis: ['setInterval'] });
  let outlet = null;
  try {
    stubFetch({ '/api/admin/channels': [CHANNELS[0]], '/api/bot-info': {} });
    outlet = await mount('channels');
    setVisibility('hidden');
    mock.timers.tick(15000);
    await tick();
    assert.equal(listCalls(), 1);
    setVisibility('visible');
    await tick();
    assert.equal(listCalls(), 2);
    mock.timers.tick(5000);
    await tick();
    assert.equal(listCalls(), 3);
  } finally { leave(outlet); mock.timers.reset(); setVisibility('visible'); }
});

test('channels poll does not repaint identical data or over an open dialog', async () => {
  mock.timers.enable({ apis: ['setInterval'] });
  let outlet = null;
  try {
    let list = [CHANNELS[0]];
    stubFetch({ '/api/admin/channels': () => list, '/api/bot-info': {} });
    outlet = await mount('channels');
    const card = q('.bank-list li');
    mock.timers.tick(5000);
    await tick();
    assert.equal(listCalls(), 2);
    assert.equal(q('.bank-list li'), card);
    list = CHANNELS;
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    document.body.appendChild(overlay);
    mock.timers.tick(5000);
    await tick();
    assert.equal(hasText('Aniqlangan kanallar'), false);
    overlay.remove();
    mock.timers.tick(5000);
    await tick();
    assert.ok(hasText('Aniqlangan kanallar'));
  } finally { leave(outlet); mock.timers.reset(); }
});

// ---------------- fragment ----------------
const FRAG = {
  is_auto_buy: true, simulation_mode: false, ton_wallet_address: 'UQAbcdefghijklmnopqrstuvwxyz0123456789',
  has_mnemonic: true, ton_wallet_mnemonic_masked: '••••••••', tonapi_key: 'SECRET-TONAPI-KEY',
  network: 'mainnet', min_ton_balance: 2, wallet_balance_ton: 3.5,
};

test('fragment secrets never prefilled or shown, placeholder says saqlangan', async () => {
  stubFetch({ '/api/admin/fragment/settings': FRAG });
  await mount('fragment');
  for (const name of ['ton_wallet_mnemonic', 'tonapi_key']) {
    assert.equal(input(name).value, '');
    assert.equal(input(name).getAttribute('type'), 'password');
    assert.match(input(name).getAttribute('placeholder'), /saqlangan/);
  }
  assert.equal(hasText('SECRET-TONAPI-KEY'), false);
  assert.equal(hasText('••'), false);
  assert.ok(hasText('3.500 TON'));
});

test('fragment unset secret shows a different placeholder', async () => {
  stubFetch({ '/api/admin/fragment/settings': { ...FRAG, has_mnemonic: false, ton_wallet_mnemonic_masked: '', tonapi_key: '' } });
  await mount('fragment');
  assert.doesNotMatch(input('ton_wallet_mnemonic').getAttribute('placeholder'), /saqlangan/);
  assert.doesNotMatch(input('tonapi_key').getAttribute('placeholder'), /saqlangan/);
});

test('fragment save omits untouched secrets, confirms (danger), sends typed ones', async () => {
  stubFetch({ '/api/admin/fragment/settings': FRAG, 'POST /api/admin/fragment/settings': { success: true } });
  await mount('fragment');
  input('min_ton_balance').value = '5';
  fire(q('form'), 'submit');
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/POST/).length, 0);
  await confirmYes();
  let b = lastBody();
  assert.equal('ton_wallet_mnemonic' in b, false);
  assert.equal('tonapi_key' in b, false);
  assert.equal(b.min_ton_balance, 5);
  assert.equal(b.is_auto_buy, true);
  assert.equal(b.network, 'mainnet');

  input('tonapi_key').value = 'NEW-KEY';
  fire(q('form'), 'submit');
  await tick();
  assert.match(dialogText(), /TonAPI kaliti/);
  assert.equal(dialogText().includes('NEW-KEY'), false);
  await confirmYes();
  b = lastBody();
  assert.equal(b.tonapi_key, 'NEW-KEY');
  assert.equal('ton_wallet_mnemonic' in b, false);
  assert.equal(input('tonapi_key').value, '');
});

test('fragment is read-only without SETTINGS_UPDATE', async () => {
  adminState.admin = { id: 2, role: 'x', permissions: ['SETTINGS_READ'] };
  stubFetch({ '/api/admin/fragment/settings': FRAG });
  await mount('fragment');
  assert.equal(btn('Saqlash'), undefined);
  assert.equal(input('tonapi_key').hasAttribute('disabled'), true);
});

test('fragment confirm names the wallet address change (Hamyon manzili)', async () => {
  stubFetch({ '/api/admin/fragment/settings': FRAG, 'POST /api/admin/fragment/settings': { success: true } });
  await mount('fragment');
  input('ton_wallet_address').value = 'UQNEWADDRESS000000000000000000000000';
  fire(q('form'), 'submit');
  await tick();
  assert.match(dialogText(), /Hamyon manzili/);
  assert.ok(dialogText().includes('UQNEWADDRESS000000000000000000000000'));
  assert.ok(dialogText().includes(FRAG.ton_wallet_address));
  await confirmYes();
  assert.equal(lastBody().ton_wallet_address, 'UQNEWADDRESS000000000000000000000000');
});

test('fragment confirm omits the address row when it is unchanged', async () => {
  stubFetch({ '/api/admin/fragment/settings': FRAG, 'POST /api/admin/fragment/settings': { success: true } });
  await mount('fragment');
  input('min_ton_balance').value = '5';
  fire(q('form'), 'submit');
  await tick();
  assert.doesNotMatch(dialogText(), /Hamyon manzili/);
});

// ---------------- health ----------------
const HEALTH = {
  overall_status: 'degraded', timestamp: '2026-11-15T10:00:00+00:00',
  bot: { status: 'online', username: 'gifthubuzbot', mode: 'polling' },
  database: { status: 'connected', latency_ms: 1.4, engine: 'postgresql' },
  redis: { status: 'connected', latency_ms: 0.8, fsm_storage: 'RedisStorage' },
  workers: { is_running: true, seconds_since_heartbeat: 3, cycle_count: 10, queue_size: 0 },
  payment_providers: {
    click: { is_active: true, circuit: 'CLOSED', status: 'healthy' },
    payme: { is_active: true, circuit: 'OPEN', status: 'degraded' },
  },
  fulfillment_providers: { fragment: { auto_buy: true, simulation_mode: false, circuit: 'CLOSED', status: 'operational' } },
  queue_depth: { pending_outbox_events: 2, unfulfilled_paid_orders: 1, in_memory_queue_size: 0 },
  failed_jobs: { exhausted_jobs: 1, retrying_jobs: 0, total_active_failures: 1 },
};
const DLQ = { success: true, jobs: [{ id: 9, job_type: 'fulfill', order_id: 5, error_message: '<i>boom</i>', attempts: 3, status: 'exhausted', created_at: '2026-11-15T09:00:00' }] };

test('health shows degraded provider and the gated endpoint is used', async () => {
  stubFetch({ '/api/v1/admin/health/system': HEALTH, '/api/v1/admin/dlq': { jobs: [] } });
  await mount('health');
  assert.ok(hasText('degraded'));
  assert.ok(hasText('payme'));
  assert.ok(hasText('Tizim qisman pasaygan'));
  assert.ok(hasText('Kutayotgan outbox'));
  assert.equal(calls(/\/api\/v1\/admin\/health\/system/).length, 1);
});

test('health refresh re-fetches', async () => {
  stubFetch({ '/api/v1/admin/health/system': HEALTH, '/api/v1/admin/dlq': { jobs: [] } });
  await mount('health');
  click('Yangilash');
  await tick();
  assert.equal(calls(/\/api\/v1\/admin\/health\/system/).length, 2);
});

test('health DLQ: error text is escaped, retry confirms, resolve needs a reason', async () => {
  stubFetch({
    '/api/v1/admin/health/system': HEALTH, '/api/v1/admin/dlq': DLQ,
    'POST /api/v1/admin/dlq/9/retry': { success: true }, 'POST /api/v1/admin/dlq/9/resolve': { success: true },
  });
  await mount('health');
  assert.ok(hasText('<i>boom</i>'));
  assert.equal(qa('i').length, 0);
  click('Qayta urinish');
  await tick();
  await confirmYes();
  assert.equal(calls(/dlq\/9\/retry/).length, 1);

  click('Hal qilindi');
  await tick();
  fire(q('.confirm-actions .btn-danger'));
  await tick();
  assert.equal(calls(/dlq\/9\/resolve/).length, 0);
  assert.ok(q('[role="dialog"]'), 'reason is required');
  q('.confirm-input').value = 'qo\'lda tuzatildi';
  fire(q('.confirm-actions .btn-danger'));
  await tick();
  assert.deepEqual(calls(/dlq\/9\/resolve/)[0].body, { reason: "qo'lda tuzatildi" });
});

test('health without ORDERS_READ does not request the DLQ', async () => {
  adminState.admin = { id: 2, role: 'x', permissions: ['SETTINGS_READ'] };
  stubFetch({ '/api/v1/admin/health/system': HEALTH });
  await mount('health');
  assert.equal(calls(/dlq/).length, 0);
});

// ---------------- admins ----------------
const ADMINS = [
  { id: 1, first_name: 'Ali', username: '@ali', role: 'super_admin', created_at: '01 Nov 2026' },
  { id: 2, first_name: 'Vali', username: '@vali', role: 'support_admin', created_at: '02 Nov 2026' },
];

test('admins: no remove or role change on yourself', async () => {
  stubFetch({ '/api/admin/admins': ADMINS });
  await mount('admins');
  const mine = qa('li').find((li) => li.textContent.includes('@ali'));
  assert.equal([...mine.querySelectorAll('button')].length, 0);
  const other = qa('li').find((li) => li.textContent.includes('@vali'));
  assert.ok([...other.querySelectorAll('button')].some((b) => b.textContent === 'Bekor qilish'));
});

test('admins: revoke is a danger confirm and calls DELETE', async () => {
  stubFetch({ '/api/admin/admins': ADMINS, 'DELETE /api/admin/admins/2': { success: true } });
  await mount('admins');
  const other = qa('li').find((li) => li.textContent.includes('@vali'));
  fire([...other.querySelectorAll('button')].find((b) => b.textContent === 'Bekor qilish'));
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.equal(calls(/DELETE/).length, 0);
  await confirmYes();
  assert.equal(calls(/DELETE \/api\/admin\/admins\/2$/).length, 1);
});

test('admins: granting super_admin is a danger confirm; other roles are a plain confirm', async () => {
  stubFetch({ '/api/admin/admins': ADMINS, 'POST /api/admin/admins': { success: true, message: 'ok' } });
  await mount('admins');
  const other = qa('li').find((li) => li.textContent.includes('@vali'));
  const sel = other.querySelector('select');
  setSelect(sel, 'super_admin');
  fire([...other.querySelectorAll('button')].find((b) => b.textContent === "Rolni o'zgartirish"));
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  assert.match(dialogText(), /Bosh administrator/);
  await confirmYes();
  assert.deepEqual(lastBody(), { identifier: '2', role: 'super_admin' });

  const form = q('form');
  form.querySelector('[name="identifier"]').value = '@yangi';
  setSelect(form.querySelector('select'), 'price_admin');
  fire(form, 'submit');
  await tick();
  assert.equal(q('.confirm-actions .btn-danger'), null);
  await confirmYes();
  assert.deepEqual(lastBody(), { identifier: '@yangi', role: 'price_admin' });
});

test('admins: appointing with an empty identifier is refused', async () => {
  stubFetch({ '/api/admin/admins': ADMINS });
  await mount('admins');
  fire(q('form'), 'submit');
  await tick();
  assert.ok(hasText('Telegram ID yoki @username kiriting'));
  assert.equal(q('[role="dialog"]'), null);
});

test('admins: read-only without ADMINS_MANAGE', async () => {
  adminState.admin = { id: 3, role: 'x', permissions: ['ADMINS_READ'] };
  stubFetch({ '/api/admin/admins': ADMINS });
  await mount('admins');
  assert.equal(q('form'), null);
  assert.equal(qa('li button').length, 0);
  assert.ok(hasText('@vali'));
});

test('broadcast timeout keeps send locked with an unknown-result notice until status refresh', async () => {
  let statusOk = false;
  stubFetch({
    '/api/admin/broadcast/latest-draft': DRAFT,
    'POST /api/admin/broadcast': () => { throw Object.assign(new Error('aborted'), { name: 'AbortError' }); },
    '/api/admin/broadcast/status': () => (statusOk ? { is_running: true, total: 5, sent: 1, blocked: 0, failed: 0 } : jsonRes(500, { detail: 'x' })),
  });
  await mount('broadcast');
  click('Yuborish');
  await tick();
  await confirmYes();
  assert.ok(hasText("Natija noma'lum"));
  const sendBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Yuborish');
  assert.ok(sendBtn.hasAttribute('disabled'));
  click('Yuborish');
  await tick();
  assert.equal(q('[role="dialog"]'), null);
  assert.equal(calls(/POST/).length, 1);
  statusOk = true;
  click('Holatni yangilash');
  await tick();
  assert.equal(sendBtn.hasAttribute('disabled'), false);
});
