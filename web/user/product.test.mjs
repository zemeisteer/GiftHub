import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let boot, appState, getProducts, tg, productScreen, topupScreen;
let dom, fetchLog, routes, listeners, mb, bb, haptics, opened;

const html = readFileSync(new URL('./new.html', import.meta.url), 'utf8');

const ME = { id: 7, first_name: 'Ali', username: 'ali', balance: 50000 };
const PRODUCTS = {
  stars_packages: [
    { amount: 50, name: '50 ⭐', price_uzs: 10350, discount_pct: 0 },
    { amount: 100, name: '100 ⭐', price_uzs: 20700, discount_pct: 2 },
    { amount: 250, name: '250 ⭐', price_uzs: 51000, discount_pct: 5 },
  ],
  premium_packages: [
    { months: 3, name: 'Premium — 3 oy', price_uzs: 142000, icon: '💎' },
    { months: 6, name: 'Premium — 6 oy', price_uzs: 210000, icon: '💎' },
  ],
  gifts: [{ id: 'bear', name: 'Teddy Bear', price_uzs: 64000, icon: '🧸', type: '3d' }],
  payment_methods: [
    { id: 'card', name: "Karta orqali to'lov", type: 'card' },
    { id: 'click', name: 'Click', type: 'official' },
    { id: 'payme', name: 'Payme', type: 'official' },
    { id: 'autopaycard', name: 'AutoPayCard (Karta)', type: 'backup' },
  ],
};
const ORDER_OK = { success: true, order_code: 'GH-1', order_id: 1, total_price: 20700, status: 'paid', new_balance: 29300 };

function jsonRes(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function stubFetch(extra = {}) {
  fetchLog = [];
  routes = { '/api/user/me': ME, '/api/products': PRODUCTS, '/api/v1/recipients': { success: true, recipients: [] }, ...extra };
  globalThis.fetch = async (url, init = {}) => {
    const entry = { url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined };
    fetchLog.push(entry);
    const r = routes[url.split('?')[0]];
    if (typeof r === 'function') return r(entry);
    if (r === undefined) return jsonRes(404, { detail: 'not found' });
    return jsonRes(200, r);
  };
}

function installTelegram({ mainButton = true } = {}) {
  haptics = [];
  opened = [];
  mb = {
    text: '', visible: false, handlers: [],
    setText(t) { this.text = t; },
    show() { this.visible = true; },
    hide() { this.visible = false; },
    showProgress() {}, hideProgress() {},
    onClick(fn) { this.handlers.push(fn); },
    offClick(fn) { this.handlers = this.handlers.filter((f) => f !== fn); },
  };
  bb = {
    visible: false, handlers: [],
    show() { this.visible = true; }, hide() { this.visible = false; },
    onClick(fn) { this.handlers.push(fn); },
    offClick(fn) { this.handlers = this.handlers.filter((f) => f !== fn); },
  };
  globalThis.Telegram = {
    WebApp: {
      initData: 'query_id=1',
      initDataUnsafe: { user: { id: 7 } },
      ready() {}, expand() {},
      MainButton: mainButton ? mb : undefined,
      BackButton: bb,
      HapticFeedback: { notificationOccurred: (k) => haptics.push(k), impactOccurred: () => haptics.push('light') },
      openLink: (u) => opened.push(u),
    },
  };
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
  ({ boot, appState, getProducts } = await import('./app.js'));
  ({ tg } = await import('../shared/tg.js'));
  ({ productScreen } = await import('./screens/product.js'));
  ({ topupScreen } = await import('./screens/topup.js'));
});

beforeEach(() => {
  tg.resetOverrides();
  listeners = {};
  installTelegram();
  location.hash = '';
  stubFetch();
});
afterEach(() => { tg.hideMainButton(); tg.backButton(null); tg.resetOverrides(); delete globalThis.Telegram; });

const tick = (ms = 15) => new Promise((r) => setTimeout(r, ms));
const outlet = () => document.getElementById('outlet');
const text = () => outlet().textContent;
const buttons = () => [...outlet().querySelectorAll('button')];
const findBtn = (label) => buttons().find((b) => b.textContent.trim() === label);
const find = (s) => text().includes(s);
const click = (label) => {
  const b = findBtn(label);
  assert.ok(b, `button "${label}" not found`);
  b.dispatchEvent(new Event('click'));
};
const calls = (path) => fetchLog.filter((e) => e.url.split('?')[0] === path).length;
const lastBody = (path) => [...fetchLog].reverse().find((e) => e.url.split('?')[0] === path)?.body;
const mainButtonText = () => mb.text;
const pay = () => Promise.all(mb.handlers.map((fn) => fn()));
const setInput = (name, value) => {
  const input = outlet().querySelector(`input[name="${name}"]`);
  assert.ok(input, `input ${name} not found`);
  input.value = value;
  input.dispatchEvent(new Event('input'));
};
function setRecipient(value) {
  click('Boshqa odamga');
  setInput('recipient', value);
}

async function openProduct(slug) {
  location.hash = `#/product/${slug}`;
  await boot();
  await tick();
}
function navigate(hash) {
  location.hash = hash;
  for (const fn of listeners.hashchange || []) fn();
}

test('product page shows server price and MainButton total', async () => {
  await openProduct('stars-100');
  assert.match(text(), /100 Stars/);
  assert.match(text(), /20 700 so'm/);
  assert.equal(mainButtonText(), "To'lash · 20 700 so'm");
  assert.equal(mb.visible, true);
  assert.equal(bb.visible, true);
});

test('unknown product slug shows not-found state', async () => {
  await openProduct('stars-999');
  assert.ok(find('Mahsulot topilmadi'));
  assert.equal(mb.visible, false);
});

test('double tap on pay sends one order with server-side fields only', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({ '/api/orders/create': async () => { await gate; return jsonRes(200, ORDER_OK); } });
  await openProduct('stars-100');
  const p = Promise.all([pay(), pay()]);
  await tick();
  release();
  await p;
  assert.equal(calls('/api/orders/create'), 1);
  const body = lastBody('/api/orders/create');
  assert.deepEqual(body, { product_type: 'stars', item_title: '100 Stars', amount: 100, recipient_username: '@ali' });
  assert.equal('total_price' in body, false);
});

test('without MainButton an in-page pay button is used, disabled while pending, one order', async () => {
  installTelegram({ mainButton: false });
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({ '/api/orders/create': async () => { await gate; return jsonRes(200, ORDER_OK); } });
  await openProduct('stars-100');
  const btn = findBtn("To'lash · 20 700 so'm");
  assert.ok(btn, 'fallback pay button');
  btn.dispatchEvent(new Event('click'));
  btn.dispatchEvent(new Event('click'));
  await tick();
  assert.equal(btn.disabled, true);
  release();
  await tick();
  assert.equal(calls('/api/orders/create'), 1);
});

test('two rendered product screens cannot double-submit (module-level guard)', async () => {
  installTelegram({ mainButton: false });
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({ '/api/orders/create': async () => { await gate; return jsonRes(200, ORDER_OK); } });
  appState.user = ME;
  location.hash = '#/product/stars-100';
  const a = await productScreen({ id: 'stars-100' });
  const b = await productScreen({ id: 'stars-100' });
  const payBtn = (root) => [...root.querySelectorAll('button')].find((x) => /^To'lash/.test(x.textContent.trim()));
  payBtn(a).dispatchEvent(new Event('click'));
  payBtn(b).dispatchEvent(new Event('click'));
  await tick();
  release();
  await tick();
  assert.equal(calls('/api/orders/create'), 1);
});

test('promo applies server-returned total', async () => {
  stubFetch({
    '/api/promo/apply': { success: true, reward_type: 'discount_percent', code: 'SALE10', original_total: 20700, new_total: 9000, discount_amount: 11700, message: 'Chegirma qo\'llandi' },
    '/api/orders/create': ORDER_OK,
  });
  await openProduct('stars-100');
  setInput('promo', ' sale10 ');
  click("Qo'llash");
  await tick();
  assert.deepEqual(lastBody('/api/promo/apply'), { code: 'sale10', order_total: 20700, product_type: 'stars' });
  assert.match(mainButtonText(), /9 000 so'm/);
  assert.ok(find("Chegirma qo'llandi"));
  await pay();
  assert.equal(lastBody('/api/orders/create').promo_code, 'SALE10');
});

test('rejected promo shows server detail and keeps original total', async () => {
  stubFetch({ '/api/promo/apply': { success: false, detail: 'Promo-kod topilmadi: XX' }, '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  setInput('promo', 'xx');
  click("Qo'llash");
  await tick();
  assert.ok(find('Promo-kod topilmadi: XX'));
  assert.equal(mainButtonText(), "To'lash · 20 700 so'm");
  await pay();
  assert.equal('promo_code' in lastBody('/api/orders/create'), false);
});

test('switching variant resets promo and shows the new server price', async () => {
  stubFetch({ '/api/promo/apply': { success: true, reward_type: 'fixed_discount', code: 'A', original_total: 20700, new_total: 9000, message: 'ok' } });
  await openProduct('stars-100');
  setInput('promo', 'a');
  click("Qo'llash");
  await tick();
  assert.match(mainButtonText(), /9 000/);
  click('250 Stars');
  assert.equal(mainButtonText(), "To'lash · 51 000 so'm");
});

test('recipient @username validated before pay', async () => {
  stubFetch({ '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  setRecipient('@a');
  await pay();
  assert.ok(find("Username noto'g'ri"));
  assert.equal(calls('/api/orders/create'), 0);
  setRecipient('friend_1');
  await pay();
  assert.equal(calls('/api/orders/create'), 1);
  assert.equal(lastBody('/api/orders/create').recipient_username, '@friend_1');
});

test('saved recipients load for the user and fill the field', async () => {
  stubFetch({
    '/api/v1/recipients': { success: true, recipients: [{ id: 1, recipient_username: 'dost_bek' }, { id: 2, recipient_username: '<bad>' }] },
    '/api/orders/create': ORDER_OK,
  });
  await openProduct('stars-100');
  click('Boshqa odamga');
  await tick();
  const req = fetchLog.find((e) => e.url.startsWith('/api/v1/recipients'));
  assert.equal(req.url, '/api/v1/recipients?user_id=7');
  assert.equal(findBtn('@<bad>'), undefined);
  click('@dost_bek');
  assert.equal(outlet().querySelector('input[name="recipient"]').value, '@dost_bek');
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '@dost_bek');
});

test('insufficient balance offers top-up', async () => {
  stubFetch({ '/api/orders/create': () => jsonRes(400, { detail: "Balansingizda mablag' yetarli emas! Joriy balans: 5 000 so'm" }) });
  await openProduct('stars-100');
  await pay();
  assert.ok(find("Balansingizda mablag' yetarli emas!"));
  assert.ok(findBtn("Hamyonni to'ldirish"));
  click("Hamyonni to'ldirish");
  assert.equal(location.hash, '#/topup');
});

test('402 is also treated as insufficient balance; other errors are shown plainly', async () => {
  stubFetch({ '/api/orders/create': () => jsonRes(402, { detail: 'Pul yetmaydi' }) });
  await openProduct('stars-100');
  await pay();
  assert.ok(findBtn("Hamyonni to'ldirish"));
  routes['/api/orders/create'] = () => jsonRes(400, { detail: 'Stars xaridlari vaqtincha o\'chirilgan.' });
  await pay();
  assert.ok(find("Stars xaridlari vaqtincha o'chirilgan."));
  assert.equal(findBtn("Hamyonni to'ldirish"), undefined);
});

test('successful pay: haptic, balance from server, cache invalidated, main button hidden, #/orders', async () => {
  stubFetch({ '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  const before = calls('/api/products');
  await pay();
  assert.ok(haptics.includes('success'));
  assert.equal(appState.balance, 29300);
  assert.equal(location.hash, '#/orders');
  assert.equal(mb.visible, false);
  await getProducts();
  assert.equal(calls('/api/products'), before + 1);
});

test('gift order sends the gift id as item_title so the server prices it', async () => {
  stubFetch({ '/api/orders/create': ORDER_OK });
  await openProduct('gift-bear');
  assert.match(text(), /Teddy Bear/);
  assert.equal(mainButtonText(), "To'lash · 64 000 so'm");
  await pay();
  assert.deepEqual(lastBody('/api/orders/create'), { product_type: 'gift', item_title: 'bear', amount: 1, recipient_username: '@ali' });
});

test('leaving the product screen hides the main button and back button', async () => {
  await openProduct('stars-100');
  assert.equal(mb.visible, true);
  navigate('#/');
  await tick();
  assert.equal(mb.visible, false);
  assert.equal(mb.handlers.length, 0);
  assert.equal(bb.visible, false);
});

test('a late promo response after leaving does not re-show the main button', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({ '/api/promo/apply': async () => { await gate; return jsonRes(200, { success: true, code: 'A', new_total: 9000 }); } });
  await openProduct('stars-100');
  setInput('promo', 'a');
  click("Qo'llash");
  navigate('#/');
  await tick();
  release();
  await tick();
  assert.equal(mb.visible, false);
});

// ---- Top-up ----

async function openTopup() {
  location.hash = '#/topup';
  await boot();
  await tick();
}

test('top-up: preset + method opens https checkout via tg.openLink', async () => {
  stubFetch({ '/api/wallet/topup': { success: true, method: 'click', checkout_url: 'https://my.click.uz/pay?x=1', amount: 50000 } });
  await openTopup();
  click('50 000');
  click('Click');
  assert.equal(mainButtonText(), "To'ldirish · 50 000 so'm");
  await pay();
  assert.deepEqual(lastBody('/api/wallet/topup'), { amount: 50000, method: 'click' });
  assert.deepEqual(opened, ['https://my.click.uz/pay?x=1']);
});

test('top-up: non-https checkout url is never opened', async () => {
  stubFetch({ '/api/wallet/topup': { success: true, checkout_url: 'http://evil.example/pay' } });
  await openTopup();
  click('Payme');
  await pay();
  assert.deepEqual(opened, []);
  assert.ok(find("To'lov havolasi noto'g'ri"));
});

test('top-up: custom amount must be an integer of at least 1 000', async () => {
  stubFetch({ '/api/wallet/topup': { success: true, checkout_url: 'https://p.uz/x' } });
  await openTopup();
  click('Click');
  click('Boshqa');
  setInput('amount', '500');
  await pay();
  assert.ok(find("Minimal to'ldirish summasi: 1 000 so'm"));
  setInput('amount', '1500.5');
  await pay();
  assert.equal(calls('/api/wallet/topup'), 0);
  setInput('amount', '15 000');
  assert.equal(mainButtonText(), "To'ldirish · 15 000 so'm");
  await pay();
  assert.deepEqual(lastBody('/api/wallet/topup'), { amount: 15000, method: 'click' });
});

test('top-up: autopaycard shows server instructions; double tap sends one request', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  stubFetch({ '/api/wallet/topup': async () => { await gate; return jsonRes(200, { success: true, method: 'autopaycard', instructions: 'Kartaga o\'tkazing: **** 6412', amount: 50000 }); } });
  await openTopup();
  click('AutoPayCard (Karta)');
  const p = Promise.all([pay(), pay()]);
  await tick();
  release();
  await p;
  await tick();
  assert.equal(calls('/api/wallet/topup'), 1);
  assert.ok(find("Kartaga o'tkazing: **** 6412"));
  assert.deepEqual(opened, []);
});

test('top-up: P2P card shows server card details and sends no request', async () => {
  stubFetch({ '/api/products': { ...PRODUCTS, card_info: { card_number: '8600 1111 2222 3333', card_holder: 'ANVAR S.', bank_name: 'TBC Bank' } } });
  await openTopup();
  click("Karta orqali to'lov");
  assert.ok(find('8600 1111 2222 3333'));
  assert.ok(find('ANVAR S.'));
  assert.equal(mb.visible, false);
  assert.equal(calls('/api/wallet/topup'), 0);
  click('Click');
  assert.equal(mb.visible, true);
});

test('top-up: no supported methods shows an empty state', async () => {
  stubFetch({ '/api/products': { ...PRODUCTS, payment_methods: [] } });
  await openTopup();
  assert.ok(find("To'lov usullari mavjud emas"));
  assert.equal(mb.visible, false);
});

test('new screens never import the versioned entry app.js', () => {
  for (const f of ['./screens/product.js', './screens/topup.js', './store.js']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /from\s+['"][^'"]*app\.js['"]|import\(\s*['"][^'"]*app\.js/, f);
  }
});

test('topupScreen and productScreen are exported functions', () => {
  assert.equal(typeof productScreen, 'function');
  assert.equal(typeof topupScreen, 'function');
});
