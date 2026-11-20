import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';

let getView, adminState, tg, field, readForm;
let fetchLog;

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const ALL = [
  'USERS_READ', 'ORDERS_READ', 'ORDERS_UPDATE', 'ORDERS_REFUND', 'PRICING_READ', 'PRICING_UPDATE',
  'PAYMENTS_READ', 'ANALYTICS_READ', 'ADMINS_READ', 'ADMINS_MANAGE', 'SETTINGS_READ', 'SETTINGS_UPDATE',
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
  ({ field, readForm } = await import('./forms.js'));
  await import('./views/pricing.js');
  await import('./views/services.js');
  await import('./views/promos.js');
  await import('./views/referral.js');
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
const submit = (sel = 'form') => fire(q(sel), 'submit');
async function mount(id) {
  const node = await getView(id)({ id });
  const outlet = document.createElement('main');
  outlet.appendChild(node);
  document.body.appendChild(outlet);
  await tick(15);
  return outlet;
}
const dialogText = () => (q('[role="dialog"]') || { textContent: '' }).textContent;
async function confirmYes(label) {
  assert.ok(q('[role="dialog"]'), 'confirm dialog expected');
  const b = label ? btn(label) : q('.confirm-actions .btn:last-child');
  fire(b);
  await tick();
}
const hasText = (s) => document.body.textContent.includes(s);

const PRICING = {
  stars_cost_ton: 0.0021, ton_rate_uzs: 14800, margin_percent: 15,
  star_unit_price_uzs: 180, fragment_stars_base_uzs: 180,
  discounts: [{ min_amount: 1000, discount_pct: 5 }],
  premium_prices: { 3: 143000, 6: 210000, 12: 380000 },
  gifts: [{ id: 'bear', name: 'Ayiq', price_uzs: 65000, icon: 'x', type: '3d' }],
};

test('pricing no longer edits gifts and does not send them (catalog lives in Sovg\'alar)', async () => {
  stubFetch({ '/api/admin/pricing': PRICING, 'POST /api/admin/pricing': { success: true } });
  await mount('pricing');
  assert.equal(input('gift_price_bear'), null);
  assert.ok(!hasText("Sovg'a narxlari"));
  setField('margin_percent', '20');
  submit();
  await tick();
  await confirmYes();
  assert.equal('gifts' in lastBody(), false);
});

// ---- forms ----
test('field builds label + named input; readForm converts types', () => {
  const form = document.createElement('form');
  form.appendChild(field({ label: 'A', name: 'a', type: 'number', value: 5, min: 0 }));
  form.appendChild(field({ label: 'B', name: 'b', type: 'number', value: '' }));
  form.appendChild(field({ label: 'C', name: 'c', value: ' hi ' }));
  form.appendChild(field({ label: 'D', name: 'd', type: 'checkbox', value: true }));
  document.body.appendChild(form);
  assert.deepEqual(readForm(form), { a: 5, b: null, c: 'hi', d: true });
});

// ---- pricing ----
test('pricing save confirms (danger) and sends the full body with numbers', async () => {
  stubFetch({ '/api/admin/pricing': PRICING, 'POST /api/admin/pricing': { success: true } });
  await mount('pricing');
  setField('margin_percent', '20');
  submit();
  await tick();
  assert.match(dialogText(), /15/);
  assert.match(dialogText(), /20/);
  assert.equal(calls(/POST/).length, 0);
  await confirmYes();
  assert.equal(calls(/POST/).length, 1);
  const b = lastBody();
  assert.equal(b.margin_percent, 20);
  assert.equal(b.ton_rate_uzs, 14800);
  assert.equal(b.stars_cost_ton, 0.0021);
  assert.equal(b.star_unit_price_uzs, 180);
  assert.deepEqual(b.discounts, [{ min_amount: 1000, discount_pct: 5 }]);
  assert.deepEqual(b.premium_prices, { 3: 143000, 6: 210000, 12: 380000 });
  assert.equal(typeof b.margin_percent, 'number');
});

test('invalid margin blocked client-side', async () => {
  stubFetch({ '/api/admin/pricing': PRICING });
  await mount('pricing');
  setField('margin_percent', '-5');
  submit();
  await tick();
  assert.ok(hasText('0 dan 100 gacha'));
  assert.ok(!q('[role="dialog"]'));
  assert.equal(calls(/POST/).length, 0);
});

test('pricing with no changes sends nothing', async () => {
  stubFetch({ '/api/admin/pricing': PRICING });
  await mount('pricing');
  submit();
  await tick();
  assert.ok(!q('[role="dialog"]'));
  assert.equal(calls(/POST/).length, 0);
});

test('pricing cancel sends nothing', async () => {
  stubFetch({ '/api/admin/pricing': PRICING });
  await mount('pricing');
  setField('margin_percent', '30');
  submit();
  await tick();
  assert.ok(q('[role="dialog"]'));
  click('Bekor qilish');
  await tick();
  assert.equal(calls(/POST/).length, 0);
});

test('pricing without PRICING_UPDATE is read only', async () => {
  adminState.admin = { id: 1, permissions: ['PRICING_READ'] };
  stubFetch({ '/api/admin/pricing': PRICING });
  await mount('pricing');
  assert.equal(btn('Saqlash'), undefined);
});

// ---- services ----
const SERVICES = [
  { id: 7, name: '<b>Netflix</b>', price_uzs: 50000, cost_uzs: 40000, category: 'Obunalar', icon: 'N', description: 'tavsif', is_active: true },
];

test('services render text-only; create validates price', async () => {
  stubFetch({ '/api/admin/services': SERVICES });
  await mount('services');
  assert.ok(hasText('<b>Netflix</b>'));
  assert.equal(qa('b').some((b) => b.children.length > 0), false);
  click("Xizmat qo'shish");
  setField('name', 'Yangi');
  setField('price_uzs', '0');
  submit();
  await tick();
  assert.ok(hasText("0 dan katta"));
  assert.equal(calls(/POST|PUT/).length, 0);
});

test('service edit sends full object after danger confirm showing price change', async () => {
  stubFetch({ '/api/admin/services': SERVICES, 'PUT /api/admin/services/7': { success: true } });
  await mount('services');
  click('Tahrirlash');
  setField('price_uzs', '60000');
  submit();
  await tick();
  assert.match(dialogText(), /50 000/);
  assert.match(dialogText(), /60 000/);
  await confirmYes();
  assert.deepEqual(lastBody(), {
    name: '<b>Netflix</b>', category: 'Obunalar', icon: 'N', price_uzs: 60000, cost_uzs: 40000,
    description: 'tavsif', is_active: true,
  });
});

test('service delete asks confirmation', async () => {
  stubFetch({ '/api/admin/services': SERVICES });
  await mount('services');
  click("O'chirish");
  await tick();
  assert.ok(q('[role="dialog"]'));
  click('Bekor qilish');
  await tick();
  assert.equal(calls(/DELETE/).length, 0);
});

test('service active toggle sends partial is_active after confirm', async () => {
  stubFetch({ '/api/admin/services': SERVICES, 'PUT /api/admin/services/7': { success: true } });
  await mount('services');
  fire(q('[role="switch"]'));
  await tick();
  await confirmYes();
  assert.deepEqual(lastBody(), { is_active: false });
});

// ---- promos ----
const PROMOS = [
  { id: 3, code: 'SALE10', reward_type: 'discount_percent', reward_value: 10, max_uses: 100, current_uses: 4, min_order_amount: 0, is_active: true },
];

test('promo delete asks confirmation', async () => {
  stubFetch({ '/api/admin/promocodes': PROMOS });
  await mount('promos');
  click("O'chirish");
  await tick();
  assert.ok(q('[role="dialog"]'));
  click('Bekor qilish');
  await tick();
  assert.equal(calls(/DELETE/).length, 0);
  click("O'chirish");
  await tick();
  await confirmYes();
  assert.equal(calls(/DELETE \/api\/admin\/promocodes\/3/).length, 1);
});

test('promo deactivate is a danger confirm then POSTs toggle', async () => {
  stubFetch({ '/api/admin/promocodes': PROMOS, 'POST /api/admin/promocodes/3/toggle': { success: true, is_active: false } });
  await mount('promos');
  click("To'xtatish");
  await tick();
  assert.ok(q('.confirm-actions .btn-danger'));
  await confirmYes();
  assert.equal(calls(/POST \/api\/admin\/promocodes\/3\/toggle/).length, 1);
});

test('promo create validates, confirms and sends typed body', async () => {
  stubFetch({ '/api/admin/promocodes': PROMOS, 'POST /api/admin/promocodes': { success: true, promo_id: 9 } });
  await mount('promos');
  click("Promo-kod qo'shish");
  setField('code', '');
  submit();
  await tick();
  assert.ok(hasText('Promo-kod nomini kiriting'));
  setField('code', 'new5');
  setField('reward_value', '150');
  submit();
  await tick();
  assert.ok(hasText('100 gacha'));
  assert.equal(calls(/POST/).length, 0);
  setField('reward_value', '5');
  setField('max_uses', '50');
  submit();
  await tick();
  await confirmYes();
  assert.deepEqual(lastBody().code, 'new5');
  assert.deepEqual(
    (({ code, reward_type, reward_value, max_uses, min_order_amount, is_active }) =>
      ({ code, reward_type, reward_value, max_uses, min_order_amount, is_active }))(calls(/POST \/api\/admin\/promocodes$/)[0].body),
    { code: 'new5', reward_type: 'discount_percent', reward_value: 5, max_uses: 50, min_order_amount: 0, is_active: true },
  );
});

test('promo code text is never parsed as markup', async () => {
  stubFetch({ '/api/admin/promocodes': [{ ...PROMOS[0], code: '<i>X</i>' }] });
  await mount('promos');
  assert.ok(hasText('<i>X</i>'));
  assert.equal(qa('i').length, 0);
});

// ---- referral ----
const REF = { bonus_percent: 5, min_purchase_uzs: 20000, auto_reward: false, require_purchase: true };

test('referral save confirms and sends all four fields (keeps toggles)', async () => {
  stubFetch({ '/api/admin/referral': REF, 'POST /api/admin/referral': { success: true } });
  await mount('referral');
  setField('bonus_percent', '7');
  submit();
  await tick();
  await confirmYes();
  assert.deepEqual(lastBody(), { bonus_percent: 7, min_purchase_uzs: 20000, auto_reward: false, require_purchase: true });
});

test('referral blocks out-of-range bonus', async () => {
  stubFetch({ '/api/admin/referral': REF });
  await mount('referral');
  setField('bonus_percent', '101');
  submit();
  await tick();
  assert.ok(hasText('0 dan 100 gacha'));
  assert.equal(calls(/POST/).length, 0);
});
