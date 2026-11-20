import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let boot, appState, getProducts, tg, productScreen, topupScreen, pickerTiming;
let defaultTiming;
let dom, fetchLog, routes, listeners, mb, bb, haptics, opened;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');

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
  routes = { '/api/gate/check': { all_passed: true, channels: [] }, '/api/user/me': ME, '/api/products': PRODUCTS, '/api/v1/recipients': { success: true, recipients: [] }, ...extra };
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
    text: '', visible: false, handlers: [], progress: false, disabled: false,
    setText(t) { this.text = t; },
    show() { this.visible = true; },
    hide() { this.visible = false; },
    showProgress() { this.progress = true; },
    hideProgress() { this.progress = false; },
    enable() { this.disabled = false; },
    disable() { this.disabled = true; },
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
  ({ productScreen, pickerTiming } = await import('./screens/product.js'));
  ({ topupScreen } = await import('./screens/topup.js'));
  defaultTiming = { ...pickerTiming };
});

beforeEach(() => {
  tg.resetOverrides();
  listeners = {};
  installTelegram();
  location.hash = '';
  stubFetch();
});
afterEach(() => {
  tg.hideMainButton(); tg.backButton(null); tg.resetOverrides(); delete globalThis.Telegram;
  Object.assign(pickerTiming, defaultTiming);
});

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
  appState.user = { ...ME };
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
    '/api/v1/recipients': { success: true, recipients: [
      { id: 1, recipient_username: 'dost_bek' }, { id: 2, recipient_username: '<bad>' },
      { id: 3, recipient_username: '123456789' }, { id: 4, recipient_username: '1abcdef' },
    ] },
    '/api/orders/create': ORDER_OK,
  });
  await openProduct('stars-100');
  click('Boshqa odamga');
  await tick();
  const req = fetchLog.find((e) => e.url.startsWith('/api/v1/recipients'));
  assert.equal(req.url, '/api/v1/recipients?user_id=7');
  assert.equal(findBtn('@<bad>'), undefined);
  assert.equal(findBtn('@1abcdef'), undefined);
  assert.ok(findBtn('123456789'), 'numeric Telegram ID chip, without @');
  click('@dost_bek');
  assert.equal(outlet().querySelector('input[name="recipient"]').value, '@dost_bek');
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '@dost_bek');
});

// --- Recipient picker (Telegram's native chooser) ---

const PICKED = { status: 'done', recipient: { id: 555000111, username: 'dost_bek', name: 'Dost Valiyev', value: '@dost_bek' } };
const PICK_PATH = '/api/recipients/picker/1234567890';
const recipientValue = () => outlet().querySelector('input[name="recipient"]').value;

function enablePicker(extra = {}) {
  const chat = { requested: [], cb: null };
  globalThis.Telegram.WebApp.requestChat = (id, cb) => { chat.requested.push(id); chat.cb = cb; };
  Object.assign(pickerTiming, { pollMs: 5, timeoutMs: 300, cancelGraceMs: 30 });
  stubFetch({
    '/api/orders/create': ORDER_OK,
    '/api/recipients/picker': { request_id: 1234567890, prepared_id: 'prep-1' },
    ...extra,
  });
  return chat;
}

test('picker: opens the native chooser, waits for the answer and fills the recipient', async () => {
  let polls = 0;
  const chat = enablePicker({ [PICK_PATH]: () => jsonRes(200, ++polls < 3 ? { status: 'pending' } : PICKED) });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(80);
  assert.deepEqual(chat.requested, ['prep-1']);
  assert.equal(recipientValue(), '@dost_bek');
  assert.match(text(), /Tanlandi: Dost Valiyev @dost_bek/);
  assert.equal(calls('/api/recipients/picker'), 1);
  assert.ok(polls >= 3);
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '@dost_bek');
});

test('picker: a person without @username is filled by ID with a clear warning', async () => {
  enablePicker({ [PICK_PATH]: { status: 'done', recipient: { id: 555000111, username: null, name: '', value: '555000111' } } });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(50);
  assert.equal(recipientValue(), '555000111');
  assert.match(text(), /@username yo'q/);
});

test('picker: names from Telegram are shown as text, never as HTML', async () => {
  enablePicker({ [PICK_PATH]: { status: 'done', recipient: { id: 555000111, username: 'dost_bek', name: '<img src=x onerror=alert(1)>', value: '@dost_bek' } } });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(50);
  assert.equal(outlet().querySelector('img'), null);
  assert.match(text(), /<img src=x onerror=alert\(1\)>/);
});

test('picker: an unusable answer value is rejected, not typed into the field', async () => {
  enablePicker({ [PICK_PATH]: { status: 'done', recipient: { id: 1, username: null, name: 'X', value: 'not a recipient!' } } });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(50);
  assert.equal(recipientValue(), '');
  assert.match(text(), /qabul qilib bo'lmadi/);
});

test('picker: an old Telegram client gets a hint and no request is made', async () => {
  stubFetch({ '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(20);
  assert.equal(calls('/api/recipients/picker'), 0);
  assert.match(text(), /Telegram'ni yangilang/);
});

test('picker: cancelling in Telegram ends the wait and leaves the field alone', async () => {
  const chat = enablePicker({ [PICK_PATH]: { status: 'pending' } });
  await openProduct('stars-100');
  click('Boshqa odamga');
  setInput('recipient', '@oldfriend');
  click('Chatdan tanlash');
  await tick(20);
  chat.cb(false);
  await tick(120);
  assert.match(text(), /bekor qilindi/);
  assert.equal(recipientValue(), '@oldfriend');
  assert.equal(findBtn('Chatdan tanlash').disabled, false);
});

test('picker: a late answer after the callback still arrives (callback true or false)', async () => {
  let polls = 0;
  const chat = enablePicker({ [PICK_PATH]: () => jsonRes(200, ++polls < 4 ? { status: 'pending' } : PICKED) });
  pickerTiming.cancelGraceMs = 250; // the answer arrives well inside the grace window
  pickerTiming.timeoutMs = 1000;
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(8);
  chat.cb(false); // some clients report false even when the bot gets the choice a moment later
  await tick(120);
  assert.equal(recipientValue(), '@dost_bek');
  assert.doesNotMatch(text(), /bekor qilindi/);
});

test('picker: server failure is shown and the button works again', async () => {
  enablePicker({ '/api/recipients/picker': () => jsonRes(502, { detail: "Telegram tanlash oynasini tayyorlay olmadi. Qo'lda yozing." }) });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(30);
  assert.match(text(), /tayyorlay olmadi/);
  assert.equal(findBtn('Chatdan tanlash').disabled, false);
});

test('picker: an expired request says so and stops polling', async () => {
  enablePicker({ [PICK_PATH]: () => jsonRes(404, { detail: 'yo\'q' }) });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(60);
  assert.match(text(), /muddati tugadi/);
  const n = calls(PICK_PATH);
  await tick(40);
  assert.equal(calls(PICK_PATH), n);
});

test('picker: a double tap makes one request', async () => {
  enablePicker({ [PICK_PATH]: PICKED });
  await openProduct('stars-100');
  click('Boshqa odamga');
  const btn = findBtn('Chatdan tanlash');
  btn.dispatchEvent(new Event('click'));
  btn.dispatchEvent(new Event('click'));
  await tick(50);
  assert.equal(calls('/api/recipients/picker'), 1);
});

test('picker: leaving the product page stops the polling', async () => {
  enablePicker({ [PICK_PATH]: { status: 'pending' } });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(30);
  navigate('#/orders');
  await tick(20);
  const n = calls(PICK_PATH);
  await tick(60);
  assert.equal(calls(PICK_PATH), n);
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

test('promo answer arriving during a failing pay never leaves the MainButton spinning', async () => {
  let releasePromo;
  const promoGate = new Promise((r) => { releasePromo = r; });
  stubFetch({
    '/api/promo/apply': async () => { await promoGate; return jsonRes(200, { success: true, code: 'A', new_total: 9000, message: 'ok' }); },
    '/api/orders/create': () => jsonRes(400, { detail: 'Xatolik' }),
  });
  await openProduct('stars-100');
  setInput('promo', 'a');
  click("Qo'llash");
  const p = pay(); // waits for the promo, MainButton shows progress
  await tick();
  assert.equal(mb.progress, true);
  releasePromo();
  await p;
  await tick();
  assert.equal(mb.progress, false);
  assert.equal(mainButtonText(), "To'lash · 9 000 so'm");
  assert.equal(lastBody('/api/orders/create').promo_code, 'A');
  assert.ok(find('Xatolik'));
});

test('unknown order outcome (network drop) blocks re-pay and points to orders', async () => {
  let creates = 0;
  stubFetch({ '/api/orders/create': () => { creates++; throw new TypeError('fetch failed'); } });
  await openProduct('stars-100');
  const meBefore = calls('/api/user/me');
  await pay();
  await tick();
  assert.ok(find("Buyurtma holati noma'lum. Buyurtmalarni tekshiring."));
  assert.equal(findBtn('Qayta urinish'), undefined);
  assert.equal(mb.progress, false);
  assert.equal(mb.disabled, true);
  assert.equal(calls('/api/user/me'), meBefore + 1, 'balance re-read');
  await pay();
  assert.equal(creates, 1, 'no second order from this screen');
  const before = calls('/api/products');
  await getProducts();
  assert.equal(calls('/api/products'), before + 1, 'products cache invalidated');
  click("Buyurtmalarni ko'rish");
  assert.equal(location.hash, '#/orders');
});

test('unknown outcome without MainButton keeps the in-page button disabled', async () => {
  installTelegram({ mainButton: false });
  stubFetch({ '/api/orders/create': () => { throw new TypeError('fetch failed'); } });
  await openProduct('stars-100');
  const btn = findBtn("To'lash · 20 700 so'm");
  btn.dispatchEvent(new Event('click'));
  await tick(30);
  assert.equal(btn.disabled, true);
  btn.dispatchEvent(new Event('click'));
  await tick();
  assert.equal(calls('/api/orders/create'), 1);
});

test('numeric Telegram ID recipient is sent as-is; usernames must start with a letter', async () => {
  stubFetch({ '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  for (const bad of ['_abcde', '1abcdef', '1234', '@ab']) {
    setRecipient(bad);
    await pay();
  }
  assert.equal(calls('/api/orders/create'), 0);
  setRecipient('123456789');
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '123456789');
});

test('balance_bonus promo shows a neutral wallet hint and is never attached', async () => {
  stubFetch({
    '/api/promo/apply': { success: true, reward_type: 'balance_bonus', code: 'BONUS', bonus_amount: 5000, message: 'Hamyoningizga +5 000 so\'m bonus qo\'shildi!' },
    '/api/orders/create': ORDER_OK,
  });
  await openProduct('stars-100');
  setInput('promo', 'bonus');
  click("Qo'llash");
  await tick();
  assert.ok(find("Bu kod hamyon uchun — Profil'da qo'llang"));
  assert.ok(!find('bonus qo\'shildi'));
  await pay();
  assert.equal('promo_code' in lastBody('/api/orders/create'), false);
});

function customStarsRoute(gates = {}) {
  return async (entry) => {
    const m = /stars_amount=(\d+)/.exec(entry.url);
    if (!m) return jsonRes(200, PRODUCTS);
    const n = Number(m[1]);
    if (gates[n]) await gates[n];
    return jsonRes(200, { ...PRODUCTS, custom_stars_calc: { amount: n, total_price_uzs: n * 200, discount_percent: 0 } });
  };
}

test('custom Stars quantity: server-priced after debounce, pay disabled until priced, body amount', async () => {
  stubFetch({ '/api/products': customStarsRoute(), '/api/orders/create': ORDER_OK });
  await openProduct('stars-100');
  click('Boshqa miqdor');
  setInput('stars_amount', '10');
  await tick(350);
  assert.equal(fetchLog.filter((e) => e.url.includes('stars_amount')).length, 0, 'below minimum: no request');
  assert.equal(mb.disabled, true);
  setInput('stars_amount', '77');
  setInput('stars_amount', '777');
  assert.equal(mb.disabled, true);
  assert.equal(mainButtonText(), "To'lash");
  await pay();
  assert.equal(calls('/api/orders/create'), 0, 'unpriced: no order');
  await tick(350);
  const priced = fetchLog.filter((e) => e.url.includes('stars_amount'));
  assert.deepEqual(priced.map((e) => e.url), ['/api/products?stars_amount=777'], 'debounced to the last value');
  assert.equal(mb.disabled, false);
  assert.equal(mainButtonText(), "To'lash · 155 400 so'm");
  assert.match(text(), /777 Stars/);
  await pay();
  assert.deepEqual(lastBody('/api/orders/create'), { product_type: 'stars', item_title: '777 Stars', amount: 777, recipient_username: '@ali' });
});

test('custom Stars quantity: a stale price answer is ignored', async () => {
  let releaseOld;
  const oldGate = new Promise((r) => { releaseOld = r; });
  stubFetch({ '/api/products': customStarsRoute({ 500: oldGate }) });
  await openProduct('stars-100');
  click('Boshqa miqdor');
  setInput('stars_amount', '500');
  await tick(350); // request for 500 is now pending
  setInput('stars_amount', '600');
  await tick(350);
  assert.equal(mainButtonText(), "To'lash · 120 000 so'm");
  releaseOld();
  await tick();
  assert.equal(mainButtonText(), "To'lash · 120 000 so'm");
  assert.match(text(), /600 Stars/);
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

test('top-up: a failed request never leaves the MainButton spinning', async () => {
  stubFetch({ '/api/wallet/topup': () => jsonRes(400, { detail: "Noma'lum to'lov usuli" }) });
  await openTopup();
  click('Click');
  await pay();
  await tick();
  assert.equal(mb.progress, false);
  assert.ok(find("Noma'lum to'lov usuli"));
  assert.equal(mainButtonText(), "To'ldirish · 50 000 so'm");
});

test('top-up: returning to the app re-reads the balance', async () => {
  await openTopup();
  assert.match(text(), /50 000 so'm/);
  routes['/api/user/me'] = { ...ME, balance: 90000 };
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
  await tick();
  assert.match(outlet().querySelector('.balance-value').textContent, /90 000 so'm/);
  assert.equal(appState.balance, 90000);
});

// --- Gifts from the real catalog ---

const BIG_ID = '5170145012310081615';
const GIFT_PRODUCTS = { ...PRODUCTS, gifts: [{ id: BIG_ID, name: 'Yurak', price_uzs: 15000, icon: '❤️', type: 'gift', stars: 15, remaining: null }] };
const GIFT_HINT = "Sovg'a «Chatdan tanlash» orqali tanlangan yoki botdan foydalangan odamga yuboriladi";

test('gift product shows recipient hint', async () => {
  stubFetch({ '/api/products': GIFT_PRODUCTS });
  await openProduct(`gift-${BIG_ID}`);
  click('Boshqa odamga');
  assert.ok(find(GIFT_HINT));
  const hint = [...outlet().querySelectorAll('.field-hint')].find((e) => e.textContent.includes(GIFT_HINT));
  assert.ok(hint);
  assert.equal(hint.closest('.recipient-other').hasAttribute('hidden'), false);
});

test('stars page has no gift recipient hint', async () => {
  await openProduct('stars-100');
  click('Boshqa odamga');
  assert.equal(find(GIFT_HINT), false);
});

test('gift page keeps 19-digit gift id as string in the hash and order body', async () => {
  stubFetch({ '/api/products': GIFT_PRODUCTS, '/api/orders/create': ORDER_OK });
  await openProduct(`gift-${BIG_ID}`);
  assert.match(text(), /Yurak/);
  assert.equal(location.hash, `#/product/gift-${BIG_ID}`);
  await pay();
  const body = lastBody('/api/orders/create');
  assert.equal(body.item_title, BIG_ID);
  assert.equal(typeof body.item_title, 'string');
});

test('unresolved recipient error from server is shown and no second order is sent', async () => {
  stubFetch({ '/api/products': GIFT_PRODUCTS, '/api/orders/create': () => jsonRes(400, { detail: "Qabul qiluvchi topilmadi. U avval botga kirgan bo'lishi kerak." }) });
  await openProduct(`gift-${BIG_ID}`);
  setRecipient('@never_used');
  await pay();
  assert.ok(find('Qabul qiluvchi topilmadi'));
  assert.equal(calls('/api/orders/create'), 1);
  assert.equal(findBtn("Hamyonni to'ldirish"), undefined);
});

test('gift to a picked person is sent by numeric ID so friends who never used the bot work', async () => {
  const chat = enablePicker({ '/api/products': GIFT_PRODUCTS, [PICK_PATH]: PICKED });
  await openProduct(`gift-${BIG_ID}`);
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(60);
  assert.deepEqual(chat.requested, ['prep-1']);
  assert.equal(recipientValue(), '@dost_bek');
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '555000111');
});

test('gift: a recipient edited after picking is sent as typed, not the picked ID', async () => {
  enablePicker({ '/api/products': GIFT_PRODUCTS, [PICK_PATH]: PICKED });
  await openProduct(`gift-${BIG_ID}`);
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(60);
  setInput('recipient', '@someone_else');
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '@someone_else');
});

test('stars to a picked person still use the @username', async () => {
  enablePicker({ [PICK_PATH]: PICKED });
  await openProduct('stars-100');
  click('Boshqa odamga');
  click('Chatdan tanlash');
  await tick(60);
  await pay();
  assert.equal(lastBody('/api/orders/create').recipient_username, '@dost_bek');
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
