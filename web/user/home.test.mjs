import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let boot, appState, getProducts, bottomNav, tg, renderLoading, renderError, renderEmpty;
let dom, fetchLog;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');

const ME = { id: 7, first_name: 'Ali', username: 'ali', balance: 12500 };
const PRODUCTS = {
  stars_packages: [
    { amount: 50, name: '50 ⭐', price_uzs: 10350, discount_pct: 0 },
    { amount: 100, name: '100 ⭐', price_uzs: 20700, discount_pct: 2 },
    { amount: 250, name: '250 ⭐', price_uzs: 51000, discount_pct: 5 },
  ],
  premium_packages: [
    { months: 3, name: 'Premium — 3 oy', price_uzs: 142000, icon: '💎' },
    { months: 6, name: 'Premium — 6 oy', price_uzs: 210000, icon: '💎' },
    { months: 12, name: 'Premium — 12 oy', price_uzs: 380000, icon: '👑' },
  ],
  gifts: [
    { id: 'bear', name: 'Teddy Bear', price_uzs: 64000, icon: '🧸', type: '3d' },
    { id: 'heart', name: 'Neon Heart', price_uzs: 85000, icon: '💖', type: '3d' },
  ],
};

const GATE_OK = { all_passed: true, channels: [] };

function jsonRes(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function stubFetch(routes) {
  fetchLog = [];
  globalThis.fetch = async (url) => {
    fetchLog.push(url);
    const r = routes[url.split('?')[0]];
    if (typeof r === 'function') return r();
    if (r === undefined) return jsonRes(404, { detail: 'not found' });
    return jsonRes(200, r);
  };
}

before(async () => {
  globalThis.__GIFTHUB_TEST__ = true;
  dom = parseHTML(html);
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.Node = dom.Node;
  globalThis.Event = dom.Event;
  globalThis.addEventListener = () => {};
  globalThis.location = {
    hash: '',
    replace(h) { this.hash = h.startsWith('#') ? h : '#' + h; },
  };
  ({ boot, appState, getProducts, bottomNav } = await import('./app.js'));
  ({ tg } = await import('../shared/tg.js'));
  ({ renderLoading, renderError, renderEmpty } = await import('../shared/state.js'));
});

beforeEach(() => {
  tg.resetOverrides();
  tg.inTelegram = true;
  tg.initData = 'query_id=1';
  location.hash = '';
  stubFetch({ '/api/gate/check': GATE_OK, '/api/user/me': ME, '/api/products': PRODUCTS });
});
afterEach(() => { tg.resetOverrides(); });

const tick = (ms = 10) => new Promise((r) => setTimeout(r, ms));
const outlet = () => document.getElementById('outlet');
const text = () => document.body.textContent;
const cards = () => [...outlet().querySelectorAll('.product-card')];
const names = () => cards().map((c) => c.querySelector('.product-name').textContent);
const find = (label) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
const click = (label) => {
  const b = find(label);
  assert.ok(b, `button "${label}" not found`);
  b.dispatchEvent(new Event('click'));
};
const tile = (cat) => outlet().querySelector(`.tile[data-cat="${cat}"]`);
const press = (el) => { assert.ok(el, 'element not found'); el.dispatchEvent(new Event('click')); };

async function bootHome() {
  await boot();
  await tick();
}

test('outside Telegram shows open-in-bot message', async () => {
  tg.inTelegram = false;
  await boot();
  assert.match(document.body.textContent, /Ilovani @gifthubuzbot ichida oching/);
  assert.equal(fetchLog.length, 0);
  assert.equal(document.getElementById('nav').childNodes.length, 0);
});

test('a failure before loading renders an error instead of a blank screen', async () => {
  const orig = tg.applyTheme;
  tg.applyTheme = () => { throw new Error('theme boom'); };
  try {
    await boot();
  } finally {
    tg.applyTheme = orig;
  }
  assert.match(outlet().textContent, /theme boom/);
  assert.ok(find('Qayta urinish'));
  assert.equal(fetchLog.length, 0);
});

test('home shows balance and product prices from server', async () => {
  await bootHome();
  assert.match(text(), /12 500 so'm/);
  assert.match(text(), /10 350 so'm/);
  assert.match(text(), /142 000 so'm/);
  assert.match(text(), /64 000 so'm/);
  assert.equal(cards().length, 8);
  assert.equal(appState.user.id, 7);
  assert.equal(appState.balance, 12500);
});

test('greets the user by name (as text) and shows the balance pill', async () => {
  stubFetch({ '/api/gate/check': GATE_OK, '/api/user/me': { ...ME, first_name: '<b>Ali</b>' }, '/api/products': PRODUCTS });
  await bootHome();
  assert.match(outlet().textContent, /Salom, <b>Ali<\/b>!/);
  assert.equal(outlet().querySelector('.home-head b'), null);
  assert.match(outlet().querySelector('.balance-pill').textContent, /12 500 so'm/);
});

test('category tiles filter the shelf and show the lowest server price', async () => {
  await bootHome();
  assert.match(tile('stars').textContent, /10 350 so'm dan/);
  assert.match(tile('premium').textContent, /142 000 so'm dan/);
  assert.match(outlet().querySelector('.shelf-title').textContent, /Tezkor xarid/);
  press(tile('premium'));
  assert.equal(cards().length, 3);
  assert.equal(tile('premium').getAttribute('aria-pressed'), 'true');
  assert.match(outlet().querySelector('.shelf-title').textContent, /Telegram Premium/);
  press(tile('gifts'));
  assert.deepEqual(names(), ['Teddy Bear', 'Neon Heart']);
  assert.equal(tile('premium').getAttribute('aria-pressed'), 'false');
  click('Hammasi');
  assert.equal(cards().length, 8);
  press(tile('stars'));
  press(tile('stars'));
  assert.equal(cards().length, 8, 'tapping the active tile again shows everything');
});

test('network failure shows retry, and retry recovers', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
  await bootHome();
  assert.ok(find('Qayta urinish'));
  assert.match(text(), /Internet aloqasi yo'q/);
  stubFetch({ '/api/gate/check': GATE_OK, '/api/user/me': ME, '/api/products': PRODUCTS });
  click('Qayta urinish');
  await tick();
  assert.match(text(), /10 350 so'm/);
});

test('product card, balance pill and referral tile navigate by hash', async () => {
  await bootHome();
  cards()[1].dispatchEvent(new Event('click'));
  assert.equal(location.hash, '#/product/stars-100');
  press(outlet().querySelector('.balance-pill'));
  assert.equal(location.hash, '#/topup');
  press(outlet().querySelector('.tile-ref'));
  assert.equal(location.hash, '#/referral');
});

test('tab routes render their screens and nav marks the active tab', async () => {
  stubFetch({ '/api/gate/check': GATE_OK, '/api/user/me': ME, '/api/products': PRODUCTS, '/api/orders/history': [] });
  location.hash = '#/orders';
  await bootHome();
  assert.match(outlet().textContent, /Buyurtmalar yo'q/);
  const current = document.querySelector('#nav [aria-current="page"]');
  assert.match(current.textContent, /Buyurtmalar/);
});

test('products are cached for 60 seconds', async () => {
  await bootHome();
  const n = fetchLog.filter((u) => u === '/api/products').length;
  await getProducts();
  assert.equal(fetchLog.filter((u) => u === '/api/products').length, n);
  await getProducts({ force: true });
  assert.equal(fetchLog.filter((u) => u === '/api/products').length, n + 1);
});

test('bottomNav has four tabs with 44px-capable buttons', () => {
  const nav = bottomNav('profile');
  const items = [...nav.querySelectorAll('button')];
  assert.deepEqual(items.map((b) => b.textContent.trim()), ['Asosiy', 'Buyurtmalar', 'Referal', 'Profil']);
  assert.equal(items[3].getAttribute('aria-current'), 'page');
});

test('no module imports the versioned entry app.js (would create a second instance)', () => {
  for (const f of ['./store.js', './screens/home.js', './screens/product.js', './screens/topup.js']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /from\s+['"][^'"]*app\.js['"]|import\(\s*['"][^'"]*app\.js/, f);
  }
});

test('state helpers render text safely', () => {
  assert.ok(renderLoading().querySelectorAll('.skeleton').length >= 4);
  let retried = 0;
  const err = renderError('<b>x</b>', () => { retried++; });
  assert.equal(err.querySelector('b'), null);
  assert.match(err.textContent, /<b>x<\/b>/);
  err.querySelector('button').dispatchEvent(new Event('click'));
  assert.equal(retried, 1);
  const empty = renderEmpty('Bo\'sh', 'Hech narsa');
  assert.match(empty.textContent, /Bo'sh/);
});
