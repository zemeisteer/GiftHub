import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let boot, tg;
let dom, fetchLog, routes, listeners, opened, tgOpened, clip;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');

const ME = {
  id: 1, first_name: 'Ali', last_name: 'Valiyev', username: 'ali', balance: 50000, photo_url: null,
  referrals_count: 3, referral_earnings: 4500, orders_count: 2, completed_orders: 1, created_at: '01 Nov 2026',
};
const PRODUCTS = {
  stars_packages: [
    { amount: 50, price_uzs: 10350, discount_pct: 0 },
    { amount: 100, price_uzs: 20700, discount_pct: 2 },
  ],
  premium_packages: [{ months: 3, name: 'Premium — 3 oy', price_uzs: 142000 }],
  gifts: [{ id: 'bear', name: 'Teddy Bear', price_uzs: 64000, icon: '🧸' }],
};
const HISTORY = [
  { id: 1, order_code: 'GH-1', product_type: 'stars', item_title: '100 Stars', amount: 100, total_price: 20700, status: 'completed', recipient_username: 'friend_one', created_at: '15 Nov, 10:00' },
  { id: 2, order_code: 'GH-2', product_type: 'gift', item_title: 'bear', amount: 1, total_price: 64000, status: 'paid', recipient_username: 'ali', created_at: '14 Nov, 09:00' },
  { id: 3, order_code: 'GH-3', product_type: 'gift', item_title: 'gone_gift', amount: 1, total_price: 1000, status: 'cancelled', recipient_username: null, created_at: '13 Nov, 08:00' },
];
const RECEIPT = {
  success: true,
  receipt: {
    receipt_number: 'GH-1', order_id: 1, date: '2026-11-15T10:00:00', paid_at: '2026-11-15T10:01:00',
    product: { product_type: 'stars', item_title: '100 Stars', quantity: 100 },
    financials: { unit_price_uzs: 207, discount_amount_uzs: 0, promo_code: null, total_price_uzs: 20700, currency: 'UZS' },
    payment: { method: 'balance', status: 'completed', provider: 'balance' },
    delivery: { recipient_username: 'friend_one', fulfillment_status: 'delivered', tx_hash: 'abc123' },
  },
};
const GATE_OK = { all_passed: true, channels: [] };
const GATE_BLOCK = {
  all_passed: false,
  channels: [
    { id: 1, title: 'GiftHub News', link: 'https://t.me/gifthub_news', passed: false },
    { id: 2, title: 'Partner', link: 'https://t.me/partner', passed: true },
  ],
};

function jsonRes(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function stubFetch(extra = {}) {
  fetchLog = [];
  routes = {
    '/api/gate/check': GATE_OK,
    '/api/user/me': ME,
    '/api/products': PRODUCTS,
    '/api/orders/history': HISTORY,
    '/api/bot-info': { username: 'gifthubuzbot' },
    '/api/referrals/analytics': { total_referrals: 3, purchasing_referrals: 2, total_earned: 4500, commission_rate: 5 },
    '/api/v1/recipients': { success: true, recipients: [] },
    '/api/v1/orders/GH-1/receipt': RECEIPT,
    ...extra,
  };
  globalThis.fetch = async (url, init = {}) => {
    const entry = { url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined };
    fetchLog.push(entry);
    const r = routes[url.split('?')[0]];
    if (typeof r === 'function') return r(entry);
    if (r === undefined) return jsonRes(404, { detail: 'not found' });
    return jsonRes(200, r);
  };
}

function installTelegram() {
  opened = [];
  tgOpened = [];
  const btn = () => ({
    handlers: [], visible: false,
    setText() {}, show() { this.visible = true; }, hide() { this.visible = false; },
    showProgress() {}, hideProgress() {}, enable() {}, disable() {},
    onClick(fn) { this.handlers.push(fn); }, offClick(fn) { this.handlers = this.handlers.filter((f) => f !== fn); },
  });
  globalThis.Telegram = {
    WebApp: {
      initData: 'query_id=1',
      initDataUnsafe: { user: { id: 1 } },
      ready() {}, expand() {},
      MainButton: btn(),
      BackButton: btn(),
      HapticFeedback: { notificationOccurred() {}, impactOccurred() {} },
      openLink: (u) => opened.push(u),
      openTelegramLink: (u) => tgOpened.push(u),
    },
  };
}

function setClipboard(impl) {
  clip = null;
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    writable: true,
    value: impl === undefined
      ? { clipboard: { writeText: async (t) => { clip = t; } } }
      : impl,
  });
}

before(async () => {
  globalThis.__GIFTHUB_TEST__ = true;
  dom = parseHTML(html);
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.Node = dom.Node;
  globalThis.Event = dom.Event;
  listeners = {};
  globalThis.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
  globalThis.location = {
    hash: '',
    replace(h) { this.hash = h.startsWith('#') ? h : '#' + h; },
  };
  ({ boot } = await import('./app.js'));
  ({ tg } = await import('../shared/tg.js'));
});

beforeEach(() => {
  tg.resetOverrides();
  listeners = {};
  installTelegram();
  setClipboard();
  location.hash = '';
  stubFetch();
});
afterEach(() => { tg.hideMainButton(); tg.backButton(null); tg.resetOverrides(); delete globalThis.Telegram; });

const tick = (ms = 15) => new Promise((r) => setTimeout(r, ms));
const outlet = () => document.getElementById('outlet');
const nav = () => document.getElementById('nav');
const text = () => outlet().textContent;
const allButtons = () => [...document.querySelectorAll('button')];
const find = (label) => allButtons().find((b) => b.textContent.trim() === label) || null;
const click = (label) => {
  const b = find(label);
  assert.ok(b, `button "${label}" not found`);
  b.dispatchEvent(new Event('click'));
};
const lastUrl = () => fetchLog[fetchLog.length - 1].url;
const urls = (path) => fetchLog.filter((e) => e.url.split('?')[0] === path);
const fire = async () => {
  for (const fn of listeners.hashchange || []) fn();
  await tick();
};
async function open(hash) {
  location.hash = hash;
  await boot();
  await tick();
}

// --- Orders ---

test('orders list shows server price, status and gift name from the products cache', async () => {
  await open('#/orders');
  assert.equal(urls('/api/orders/history')[0].url, '/api/orders/history?status=all');
  assert.match(text(), /GH-1/);
  assert.match(text(), /20 700 so'm/);
  assert.match(text(), /Bajarildi/);
  assert.match(text(), /Teddy Bear/); // gift id "bear" -> product name
  assert.match(text(), /gone_gift/); // unknown gift id -> raw title
  assert.match(text(), /Bekor qilindi/);
  assert.match(nav().querySelector('[aria-current="page"]').textContent, /Buyurtmalar/);
});

test('orders filter by status', async () => {
  await open('#/orders');
  click('Jarayonda');
  await tick();
  assert.match(lastUrl(), /status=pending/);
  assert.equal(find('Jarayonda').getAttribute('aria-pressed'), 'true');
  click('Bajarildi');
  await tick();
  assert.match(lastUrl(), /status=done/);
  click('Bekor qilingan');
  await tick();
  assert.match(lastUrl(), /status=cancel/);
});

test('orders search filters by code and product name', async () => {
  await open('#/orders');
  const input = outlet().querySelector('input[type="search"]');
  input.value = 'teddy';
  input.dispatchEvent(new Event('input'));
  assert.doesNotMatch(text(), /GH-1/);
  assert.match(text(), /GH-2/);
  input.value = 'zzz';
  input.dispatchEvent(new Event('input'));
  assert.match(text(), /Buyurtmalar yo'q/);
});

test('empty history shows empty state; failure shows retry', async () => {
  stubFetch({ '/api/orders/history': [] });
  await open('#/orders');
  assert.match(text(), /Buyurtmalar yo'q/);
  stubFetch({ '/api/orders/history': () => jsonRes(500, { detail: 'boom' }) });
  click('Jarayonda');
  await tick();
  assert.match(text(), /boom/);
  stubFetch();
  click('Qayta urinish');
  await tick();
  assert.match(text(), /GH-1/);
});

test('receipt opens for completed order', async () => {
  await open('#/orders');
  click('Chek');
  assert.equal(location.hash, '#/orders/GH-1');
  await fire();
  assert.match(lastUrl(), /\/receipt$/);
  assert.equal(lastUrl(), '/api/v1/orders/GH-1/receipt');
  assert.match(text(), /20 700 so'm/);
  assert.match(text(), /@friend_one/);
  assert.match(text(), /abc123/);
  assert.match(nav().querySelector('[aria-current="page"]').textContent, /Buyurtmalar/);
  assert.equal(globalThis.Telegram.WebApp.BackButton.visible, true);
  click('Chekni nusxalash');
  await tick();
  assert.match(clip, /GH-1/);
  assert.match(clip, /20 700 so'm/);
});

test('receipt load failure shows retry', async () => {
  stubFetch({ '/api/v1/orders/GH-9/receipt': () => jsonRes(404, { detail: 'Buyurtma topilmadi.' }) });
  await open('#/orders/GH-9');
  assert.match(text(), /Buyurtma topilmadi/);
  assert.ok(find('Qayta urinish'));
});

test('buy again pre-fills product screen', async () => {
  stubFetch({
    '/api/v1/orders/GH-1/buy-again-details': {
      success: true, product_type: 'stars', item_title: '100 Stars', amount: 100, recipient_username: 'friend_one', current_total_price_uzs: 99,
    },
  });
  await open('#/orders');
  click('Yana sotib olish');
  await tick();
  assert.equal(urls('/api/v1/orders/GH-1/buy-again-details').length, 1);
  assert.equal(location.hash, '#/product/stars-100');
  await fire();
  assert.equal(outlet().querySelector('input[name="recipient"]').value, '@friend_one');
  assert.equal(find('Boshqa odamga').getAttribute('aria-pressed'), 'true');
  // The price is the product screen's server price, never the old order's.
  assert.match(text(), /20 700 so'm/);
  assert.doesNotMatch(text(), /\b99 so'm/);
});

test('buy again for a gift maps the gift id; self recipient stays self', async () => {
  stubFetch({
    '/api/v1/orders/GH-2/buy-again-details': { success: true, product_type: 'gift', item_title: 'bear', amount: 1, recipient_username: 'ali' },
  });
  await open('#/orders');
  const btn = [...outlet().querySelectorAll('.order-row')][1].querySelector('button[data-act="again"]');
  btn.dispatchEvent(new Event('click'));
  await tick();
  assert.equal(location.hash, '#/product/gift-bear');
  await fire();
  assert.equal(find("O'zimga").getAttribute('aria-pressed'), 'true');
});

test('buy again for a custom Stars amount opens the custom quantity', async () => {
  stubFetch({
    '/api/v1/orders/GH-1/buy-again-details': { success: true, product_type: 'stars', item_title: '105 Stars', amount: 105, recipient_username: null },
    '/api/products': (e) => (e.url.includes('stars_amount=105')
      ? jsonRes(200, { custom_stars_calc: { amount: 105, total_price_uzs: 22000, discount_percent: 0 } })
      : jsonRes(200, PRODUCTS)),
  });
  await open('#/orders');
  click('Yana sotib olish');
  await tick();
  assert.equal(location.hash, '#/product/stars-custom');
  await fire();
  await tick(350);
  assert.equal(outlet().querySelector('input[name="stars_amount"]').value, '105');
  assert.match(text(), /22 000 so'm/);
});

test('buy again for a product no longer sold shows a notice', async () => {
  stubFetch({
    '/api/v1/orders/GH-3/buy-again-details': { success: true, product_type: 'gift', item_title: 'gone_gift', amount: 1 },
  });
  await open('#/orders');
  const btn = [...outlet().querySelectorAll('.order-row')][2].querySelector('button[data-act="again"]');
  btn.dispatchEvent(new Event('click'));
  await tick();
  assert.equal(location.hash, '#/orders');
  assert.match(text(), /hozir sotuvda yo'q/);
});

// --- Gate ---

test('gate blocks app until subscribed', async () => {
  stubFetch({ '/api/gate/check': GATE_BLOCK });
  await open('#/');
  assert.ok(find("Obuna bo'lish"));
  assert.equal(find('Asosiy'), null);
  assert.equal(nav().hidden, true);
  assert.match(text(), /GiftHub News/);
  click("Obuna bo'lish");
  assert.deepEqual(tgOpened, ['https://t.me/gifthub_news']);
  // Still not subscribed: stays on the gate.
  click('Tekshirish');
  await tick();
  assert.equal(find('Asosiy'), null);
  assert.match(document.body.textContent, /hali obuna bo'lmagansiz/);
  // Subscribed now: the app loads.
  routes['/api/gate/check'] = GATE_OK;
  click('Tekshirish');
  await tick();
  assert.ok(find('Asosiy'));
  assert.equal(nav().hidden, false);
  assert.match(text(), /20 700 so'm/);
});

test('gate check failure shows retry and never lets the user in', async () => {
  stubFetch({ '/api/gate/check': () => jsonRes(500, { detail: 'gate boom' }) });
  await open('#/');
  assert.match(text(), /gate boom/);
  assert.equal(find('Asosiy'), null);
  routes['/api/gate/check'] = GATE_OK;
  click('Qayta urinish');
  await tick();
  assert.ok(find('Asosiy'));
});

test('gate ignores non-telegram channel links except https via openLink', async () => {
  stubFetch({
    '/api/gate/check': {
      all_passed: false,
      channels: [
        { id: 1, title: 'Site', link: 'https://example.com/join', passed: false },
        { id: 2, title: 'Bad', link: 'javascript:alert(1)', passed: false },
      ],
    },
  });
  await open('#/');
  const btns = allButtons().filter((b) => b.textContent.trim() === "Obuna bo'lish");
  btns.forEach((b) => b.dispatchEvent(new Event('click')));
  assert.deepEqual(opened, ['https://example.com/join']);
  assert.deepEqual(tgOpened, []);
});

// --- Referral ---

// Runs first: the bot username is cached per module once /api/bot-info succeeds.
test('referral uses defaults when bot-info and analytics fail', async () => {
  stubFetch({ '/api/bot-info': () => jsonRes(500, {}), '/api/referrals/analytics': () => jsonRes(500, {}) });
  await open('#/referral');
  assert.equal(outlet().querySelector('input[name="ref_link"]').value, 'https://t.me/gifthubuzbot?start=ref_1');
  assert.match(text(), /4 500 so'm/); // /api/user/me referral_earnings
  assert.doesNotMatch(text(), /undefined|NaN/);
});

test('referral link copy', async () => {
  await open('#/referral');
  assert.equal(outlet().querySelector('input[name="ref_link"]').value, 'https://t.me/gifthubuzbot?start=ref_1');
  click('Nusxa olish');
  await tick();
  assert.equal(clip, 'https://t.me/gifthubuzbot?start=ref_1');
  assert.match(document.body.textContent, /Nusxa olindi/);
  assert.match(text(), /4 500 so'm/);
  assert.match(text(), /5%/);
});

test('referral copy falls back to selecting the input', async () => {
  setClipboard({});
  let copied = 0;
  document.execCommand = (cmd) => { if (cmd === 'copy') copied++; return true; };
  try {
    await open('#/referral');
    click('Nusxa olish');
    await tick();
    assert.equal(copied, 1);
    assert.match(document.body.textContent, /Nusxa olindi/);
  } finally {
    delete document.execCommand;
  }
});

// --- Profile ---

test('profile shows user data, balance and links', async () => {
  await open('#/profile');
  assert.match(text(), /Ali Valiyev/);
  assert.match(text(), /@ali/);
  assert.match(text(), /01 Nov 2026/);
  assert.match(text(), /50 000 so'm/);
  click("Qo'llab-quvvatlash");
  click('Yangiliklar kanali');
  assert.deepEqual(tgOpened, ['https://t.me/gifthub_support', 'https://t.me/gifthub_news']);
  click("To'ldirish");
  assert.equal(location.hash, '#/topup');
});

test('profile wallet promo code applies with order_total 0 and refreshes balance', async () => {
  await open('#/profile');
  routes['/api/promo/apply'] = { success: true, reward_type: 'balance_bonus', message: '10 000 so\'m bonus!' };
  routes['/api/user/me'] = { ...ME, balance: 60000 };
  const input = outlet().querySelector('input[name="wallet_promo"]');
  input.value = 'WELCOME5K';
  click("Qo'llash");
  await tick();
  const req = urls('/api/promo/apply')[0];
  assert.equal(req.method, 'POST');
  assert.deepEqual(req.body, { code: 'WELCOME5K', order_total: 0, product_type: 'all' });
  assert.match(text(), /10 000 so'm bonus!/);
  assert.match(text(), /60 000 so'm/);
  assert.equal(input.value, '');
});

test('profile wallet promo shows server rejection', async () => {
  await open('#/profile');
  routes['/api/promo/apply'] = { success: false, detail: 'Promo-kod topilmadi: XX' };
  outlet().querySelector('input[name="wallet_promo"]').value = 'XX';
  click("Qo'llash");
  await tick();
  assert.match(text(), /Promo-kod topilmadi: XX/);
});

test('no new screen imports the versioned entry app.js', () => {
  for (const f of ['orders', 'referral', 'profile', 'gate']) {
    const src = readFileSync(new URL(`./screens/${f}.js`, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /from\s+['"][^'"]*app\.js['"]|import\(\s*['"][^'"]*app\.js/, f);
  }
});
