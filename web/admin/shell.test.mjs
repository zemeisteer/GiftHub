import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let boot, go, VIEW_MODULES, NAV, renderNav, confirmDialog, registerView, setBadge, adminState, tg;
let dom, fetchLog;

const html = readFileSync(new URL('./new.html', import.meta.url), 'utf8');

const ALL_PERMS = [
  'USERS_READ', 'ORDERS_READ', 'ORDERS_UPDATE', 'ORDERS_REFUND', 'PRICING_READ', 'PRICING_UPDATE',
  'PAYMENTS_READ', 'BROADCAST_CREATE', 'BROADCAST_SEND', 'SUPPORT_READ', 'SUPPORT_REPLY',
  'ANALYTICS_READ', 'ADMINS_READ', 'ADMINS_MANAGE', 'SETTINGS_READ', 'SETTINGS_UPDATE',
];
const SUPER = { id: 1, first_name: 'Ali', role: 'super_admin', permissions: ALL_PERMS };

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
    replace(hh) { this.hash = hh.startsWith('#') ? hh : '#' + hh; },
  };
  ({ boot, go, VIEW_MODULES } = await import('./admin.js'));
  ({ NAV, renderNav } = await import('./nav.js'));
  ({ confirmDialog } = await import('./confirm.js'));
  ({ registerView, setBadge, adminState } = await import('./registry.js'));
  ({ tg } = await import('../shared/tg.js'));
});

beforeEach(() => {
  tg.resetOverrides();
  tg.inTelegram = true;
  tg.initData = 'query_id=1';
  location.hash = '';
  adminState.admin = null;
  stubFetch({ '/api/admin/me': SUPER, '/api/v1/admin/orders/problematic': { counts: { total_problematic: 0 } } });
});
afterEach(() => { tg.resetOverrides(); });

const tick = (ms = 10) => new Promise((r) => setTimeout(r, ms));
const outlet = () => document.getElementById('outlet');
const navEl = () => document.getElementById('nav');
const text = () => document.body.textContent;
const find = (label) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
const click = (label) => {
  const b = find(label);
  assert.ok(b, `button "${label}" not found`);
  b.dispatchEvent(new Event('click'));
};
const key = (target, k, extra = {}) => {
  const ev = new Event('keydown', { bubbles: true, cancelable: true });
  ev.key = k;
  Object.assign(ev, extra);
  let prevented = false;
  ev.preventDefault = () => { prevented = true; };
  target.dispatchEvent(ev);
  return () => prevented;
};

test('nav hides items without permission', () => {
  const n = renderNav({ permissions: ['ANALYTICS_READ'] }, 'dash');
  assert.equal(n.textContent.includes('Adminlar'), false);
  assert.equal(n.textContent.includes('Narxlar'), false);
  assert.ok(n.textContent.includes('Bosh sahifa'));
  // groups without visible items are not rendered
  assert.equal(n.textContent.includes('Marketing'), false);
});

test('NAV has the legacy sections in four groups, in spec order', () => {
  assert.deepEqual(NAV.map((g) => g.group), ['Asosiy', 'Savdo', 'Marketing', 'Tizim']);
  assert.deepEqual(NAV.map((g) => g.items.map((i) => i.id)), [
    ['dash', 'orders', 'users'],
    ['pricing', 'services', 'promos', 'referral'],
    ['broadcast', 'channels', 'gate'],
    ['payments', 'fragment', 'health', 'admins'],
  ]);
  const items = NAV.flatMap((g) => g.items);
  assert.equal(items.length, 14);
  for (const i of items) {
    assert.ok(i.label && i.icon && ALL_PERMS.includes(i.perm), i.id);
  }
});

test('super admin sees every item; active item is marked', () => {
  const n = renderNav(SUPER, 'orders');
  const links = [...n.querySelectorAll('a.nav-item')];
  assert.equal(links.length, 14);
  const cur = n.querySelector('[aria-current="page"]');
  assert.match(cur.textContent, /Buyurtmalar/);
  assert.equal(cur.getAttribute('href'), '#/orders');
});

test('outside Telegram shows open-in-bot message', async () => {
  tg.inTelegram = false;
  await boot();
  assert.match(text(), /oching/);
  assert.equal(fetchLog.length, 0);
  assert.equal(navEl().childNodes.length, 0);
});

test('401/403 on the profile shows full-screen no-access without nav', async () => {
  stubFetch({ '/api/admin/me': () => jsonRes(403, { detail: 'Ruxsat berilmagan' }) });
  await boot();
  await tick();
  assert.match(outlet().textContent, /Bu bo'lim uchun ruxsatingiz yo'q/);
  assert.equal(navEl().childNodes.length, 0);
  assert.equal(find('Qayta urinish'), undefined);
});

test('a network failure on the profile shows retry, and retry recovers', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
  await boot();
  assert.ok(find('Qayta urinish'));
  stubFetch({ '/api/admin/me': SUPER });
  click('Qayta urinish');
  await tick();
  assert.ok(navEl().querySelectorAll('a.nav-item').length > 0);
});

test('boot renders the nav and a view without a module as "Tez orada" placeholder', async () => {
  // Every real nav item has a module now, so simulate a not-yet-built section by dropping its entry.
  // (No view is registered for "admins" at this point in the file; later tests register stubs.)
  const saved = VIEW_MODULES.admins;
  delete VIEW_MODULES.admins;
  try {
    stubFetch({ '/api/admin/me': { ...SUPER, permissions: ['ADMINS_READ'] } });
    await boot();
    await tick();
    assert.equal(adminState.admin.id, 1);
    assert.equal(navEl().querySelectorAll('a.nav-item').length, 1);
    assert.match(outlet().textContent, /Tez orada/);
    assert.match(navEl().querySelector('[aria-current="page"]').textContent, /Adminlar/);
  } finally {
    VIEW_MODULES.admins = saved;
  }
});

test('default landing is the first item the admin may see', async () => {
  stubFetch({ '/api/admin/me': { id: 2, role: 'support_admin', permissions: ['ORDERS_READ', 'USERS_READ'] } });
  await boot();
  await tick();
  assert.match(navEl().querySelector('[aria-current="page"]').textContent, /Buyurtmalar/);
});

test('direct hash to a view the server forbids shows no-access, no retry', async () => {
  await boot();
  await tick();
  registerView('admins', async () => {
    const { api } = await import('../shared/api.js');
    return api('/api/admin/admins');
  });
  stubFetch({ '/api/admin/admins': () => jsonRes(403, { detail: 'Yetarli huquq mavjud emas' }) });
  await go('#/admins');
  await tick();
  assert.match(outlet().textContent, /ruxsatingiz yo'q/);
  assert.equal(find('Qayta urinish'), undefined);
});

test('direct hash to a view outside the permissions is refused without loading it', async () => {
  stubFetch({ '/api/admin/me': { id: 2, role: 'support_admin', permissions: ['ORDERS_READ', 'USERS_READ'] } });
  let loaded = 0;
  registerView('admins', async () => { loaded++; return document.createElement('div'); });
  await boot();
  await tick();
  await go('#/admins');
  await tick();
  assert.match(outlet().textContent, /ruxsatingiz yo'q/);
  assert.equal(loaded, 0);
});

test('other view errors show a retry that re-renders the view', async () => {
  await boot();
  await tick();
  let calls = 0;
  registerView('users', async () => {
    calls++;
    if (calls === 1) throw new Error('boom');
    const d = document.createElement('div');
    d.textContent = 'users ok';
    return d;
  });
  await go('#/users');
  await tick();
  assert.match(outlet().textContent, /boom/);
  click('Qayta urinish');
  await tick();
  assert.match(outlet().textContent, /users ok/);
});

test('registered view gets route params; unknown section shows not-found', async () => {
  await boot();
  await tick();
  let seen = null;
  registerView('orders', async (params) => {
    seen = params;
    const d = document.createElement('div');
    d.textContent = 'orders view';
    return d;
  });
  await go('#/orders/GH-1');
  await tick();
  assert.deepEqual(seen, { id: 'orders', sub: 'GH-1' });
  assert.match(outlet().textContent, /orders view/);
  await go('#/nope');
  await tick();
  assert.match(outlet().textContent, /Bo'lim topilmadi/);
});

test('problem-orders count becomes a badge on Buyurtmalar', async () => {
  stubFetch({ '/api/admin/me': SUPER, '/api/v1/admin/orders/problematic': { counts: { total_problematic: 3 } } });
  await boot();
  await tick(30);
  const badge = navEl().querySelector('a[href="#/orders"] .nav-badge');
  assert.equal(badge.textContent, '3');
  setBadge('orders', 0);
  assert.equal(navEl().querySelector('a[href="#/orders"] .nav-badge').hasAttribute('hidden'), true);
});

test('menu button toggles the bottom sheet, Esc and link click close it', async () => {
  await boot();
  await tick();
  const wrap = navEl().querySelector('.admin-nav');
  const btn = navEl().querySelector('.menu-btn');
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
  btn.dispatchEvent(new Event('click'));
  assert.ok(wrap.classList.contains('open'));
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  key(wrap, 'Escape');
  assert.equal(wrap.classList.contains('open'), false);
  btn.dispatchEvent(new Event('click'));
  navEl().querySelector('a.nav-item').dispatchEvent(new Event('click'));
  assert.equal(wrap.classList.contains('open'), false);
});

test('confirm resolves false on cancel and removes itself', async () => {
  const p = confirmDialog({ title: 'X' });
  assert.ok(document.querySelector('[role="dialog"]'));
  click('Bekor qilish');
  assert.equal(await p, false);
  assert.equal(document.querySelector('[role="dialog"]'), null);
});

test('confirm resolves true on the confirm button, default and custom label', async () => {
  let p = confirmDialog({ title: 'X', text: 'Aniqmi?' });
  assert.match(text(), /Aniqmi\?/);
  click('Tasdiqlash');
  assert.equal(await p, true);
  p = confirmDialog({ title: 'X', confirmLabel: "O'chirish", danger: true });
  const b = find("O'chirish");
  assert.ok(b.classList.contains('btn-danger'));
  click("O'chirish");
  assert.equal(await p, true);
});

test('non-danger confirm button is not red', async () => {
  const p = confirmDialog({ title: 'X' });
  assert.equal(find('Tasdiqlash').classList.contains('btn-danger'), false);
  click('Bekor qilish');
  await p;
});

test('Esc cancels the confirm dialog', async () => {
  const p = confirmDialog({ title: 'X' });
  key(document.querySelector('[role="dialog"]'), 'Escape');
  assert.equal(await p, false);
});

test('Esc works with focus on body (handler is document-level) and is removed afterwards', async () => {
  const p = confirmDialog({ title: 'X' });
  key(document.body, 'Escape');
  assert.equal(await p, false);
  const q = confirmDialog({ title: 'Y' });
  click('Bekor qilish');
  assert.equal(await q, false);
  assert.equal(document.querySelector('[role="dialog"]'), null);
  assert.equal(key(document.body, 'Escape')(), false);
});

test('dialog title ids are unique and box is focusable', async () => {
  const a = confirmDialog({ title: 'A' });
  const idA = document.querySelector('[role="dialog"]').getAttribute('aria-labelledby');
  click('Bekor qilish');
  await a;
  const b = confirmDialog({ title: 'B' });
  const box = document.querySelector('[role="dialog"]');
  assert.notEqual(box.getAttribute('aria-labelledby'), idA);
  assert.equal(box.getAttribute('tabindex'), '-1');
  click('Bekor qilish');
  await b;
});

test('mobile topbar is fixed and the outlet leaves room for it', () => {
  const css = readFileSync(new URL('./admin.css', import.meta.url), 'utf8');
  assert.match(css, /\.topbar\s*\{[^}]*position:\s*fixed;[^}]*top:\s*0/);
  assert.doesNotMatch(css, /position:\s*sticky/);
  assert.match(css, /\.outlet\s*\{[^}]*padding:\s*calc\(var\(--topbar-h\)/);
});

test('Tab is trapped inside the confirm dialog', async () => {
  const p = confirmDialog({ title: 'X' });
  const dlg = document.querySelector('[role="dialog"]');
  const cancel = find('Bekor qilish');
  const ok = find('Tasdiqlash');
  const focused = [];
  cancel.focus = () => focused.push('cancel');
  ok.focus = () => focused.push('ok');
  Object.defineProperty(document, 'activeElement', { configurable: true, get: () => ok });
  assert.equal(key(dlg, 'Tab')(), true);
  assert.deepEqual(focused, ['cancel']);
  Object.defineProperty(document, 'activeElement', { configurable: true, get: () => cancel });
  assert.equal(key(dlg, 'Tab', { shiftKey: true })(), true);
  assert.deepEqual(focused, ['cancel', 'ok']);
  delete document.activeElement;
  click('Bekor qilish');
  await p;
});

test('confirm text is rendered as text, never as HTML', async () => {
  const p = confirmDialog({ title: '<b>t</b>', text: '<img src=x>' });
  assert.equal(document.querySelector('[role="dialog"] img'), null);
  assert.match(text(), /<img src=x>/);
  click('Bekor qilish');
  await p;
});

test('no module imports the versioned entry admin.js', () => {
  for (const f of readdirSync(new URL('.', import.meta.url))) {
    if (!f.endsWith('.js') || f === 'admin.js') continue;
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /from\s+['"][^'"]*admin\.js['"]|import\(\s*['"][^'"]*admin\.js/, f);
  }
});
