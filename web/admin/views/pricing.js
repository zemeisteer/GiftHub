// Narxlar: Stars/TON pricing, Stars discounts and Premium prices (gifts live in the Sovg'alar view).
// GET /api/admin/pricing (PRICING_READ), POST /api/admin/pricing (PRICING_UPDATE, server-enforced).
// The POST resets stars_cost_ton / ton_rate_uzs / margin_percent to defaults when omitted and
// replaces discounts / premium_prices whole, so the whole current state is always sent.
// `gifts` is deliberately omitted: the server leaves the legacy gifts_json untouched then.
import { h, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, showToast } from './ui.js';
import { field, readForm, readField, firstProblem, numberProblem, formError, summarize } from '../forms.js';

const PREMIUM_MONTHS = ['3', '6', '12'];
const num = (v, d) => (Number.isFinite(Number(v)) && v !== null && v !== '' ? Number(v) : d);
const som = (v) => formatSom(v);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function discountRow(d, editable, onRemove) {
  const min = field({ label: 'Minimal miqdor (Stars)', name: 'disc_min', type: 'number', value: d.min_amount, min: 1, step: 1, attrs: editable ? {} : { disabled: true } });
  const pct = field({ label: 'Chegirma (%)', name: 'disc_pct', type: 'number', value: d.discount_pct, min: 0, max: 100, step: 'any', attrs: editable ? {} : { disabled: true } });
  const row = h('div', { class: 'disc-row' }, min, pct,
    editable ? h('button', { type: 'button', class: 'btn btn-secondary btn-sm', 'aria-label': "Chegirmani olib tashlash", onclick: () => onRemove(row) }, "Olib tashlash") : null);
  row.read = () => ({ min: readField(min), pct: readField(pct) });
  return row;
}

async function render() {
  const editable = can('PRICING_UPDATE');
  const data = (await api('/api/admin/pricing')) || {};
  const dis = editable ? {} : { disabled: true };

  const orig = {
    stars_cost_ton: num(data.stars_cost_ton, 0.0021),
    ton_rate_uzs: num(data.ton_rate_uzs, 14800),
    margin_percent: num(data.margin_percent, 20),
    star_unit_price_uzs: num(data.star_unit_price_uzs, num(data.fragment_stars_base_uzs, 180)),
    discounts: Array.isArray(data.discounts) ? data.discounts : [],
    premium_prices: data.premium_prices || {},
  };
  const origPrem = (m) => num(orig.premium_prices[m], 0);

  const error = formError();
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');

  const discBody = h('div', { class: 'disc-list' });
  const rows = [];
  const removeRow = (row) => {
    rows.splice(rows.indexOf(row), 1);
    row.remove();
  };
  const addRow = (d) => {
    const row = discountRow(d, editable, removeRow);
    rows.push(row);
    discBody.appendChild(row);
  };
  orig.discounts.forEach(addRow);

  const form = h('form', { class: 'pricing-form', novalidate: true },
    h('section', { class: 'card card-form' },
      h('h2', { class: 'section-title' }, 'Stars'),
      h('div', { class: 'form-grid' },
        field({ label: "1 Stars tannarxi (so'm)", name: 'star_unit_price_uzs', type: 'number', value: orig.star_unit_price_uzs, min: 0, step: 'any', attrs: dis }),
        field({ label: 'Marja (%)', name: 'margin_percent', type: 'number', value: orig.margin_percent, min: 0, max: 100, step: 'any', attrs: dis }),
        field({ label: "TON kursi (so'm)", name: 'ton_rate_uzs', type: 'number', value: orig.ton_rate_uzs, min: 0, step: 'any', attrs: dis }),
        field({ label: '1 Stars narxi (TON)', name: 'stars_cost_ton', type: 'number', value: orig.stars_cost_ton, min: 0, step: 'any', attrs: dis }))),
    h('section', { class: 'card card-form' },
      h('div', { class: 'section-head' },
        h('h2', { class: 'section-title' }, 'Stars chegirmalari'),
        editable ? h('button', { type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => addRow({ min_amount: 2500, discount_pct: 10 }) }, "Chegirma qo'shish") : null),
      discBody),
    h('section', { class: 'card card-form' },
      h('h2', { class: 'section-title' }, 'Premium narxlari'),
      h('div', { class: 'form-grid' },
        PREMIUM_MONTHS.map((m) => field({ label: `${m} oy (so'm)`, name: `prem_${m}`, type: 'number', value: origPrem(m) || '', min: 1, step: 1, attrs: dis })))),
    error,
    editable ? h('div', { class: 'form-actions' }, submit) : h('p', { class: 'muted small' }, "O'zgartirish uchun ruxsat yo'q"));

  // Collect the new state. Returns { body } or { problem }.
  function collect() {
    const f = readForm(form);
    const scalar = firstProblem([
      [f.star_unit_price_uzs, { label: '1 Stars tannarxi', gt: 0 }],
      [f.margin_percent, { label: 'Marja', min: 0, max: 100 }],
      [f.ton_rate_uzs, { label: 'TON kursi', gt: 0 }],
      [f.stars_cost_ton, { label: '1 Stars narxi (TON)', gt: 0 }],
    ]);
    if (scalar) return { problem: scalar };

    const discounts = [];
    for (const row of rows) {
      const { min, pct } = row.read();
      if (min === null && pct === null) continue;
      const p = firstProblem([
        [min, { label: 'Chegirma uchun minimal miqdor', min: 1, int: true }],
        [pct, { label: 'Chegirma foizi', gt: 0, max: 100 }],
      ]);
      if (p) return { problem: p };
      discounts.push({ min_amount: min, discount_pct: pct });
    }

    const premium_prices = { ...orig.premium_prices };
    for (const m of PREMIUM_MONTHS) {
      const v = f[`prem_${m}`];
      const p = numberProblem(v, { label: `${m} oylik Premium narxi`, gt: 0, int: true });
      if (p) return { problem: p };
      premium_prices[m] = v;
    }

    return {
      body: {
        stars_cost_ton: f.stars_cost_ton,
        ton_rate_uzs: f.ton_rate_uzs,
        margin_percent: f.margin_percent,
        star_unit_price_uzs: f.star_unit_price_uzs,
        discounts,
        premium_prices,
      },
    };
  }

  function changesOf(body) {
    const out = [];
    const scalar = (key, label, fmt = String) => {
      if (body[key] !== orig[key]) out.push([label, fmt(orig[key]), fmt(body[key])]);
    };
    scalar('star_unit_price_uzs', '1 Stars tannarxi', som);
    scalar('margin_percent', 'Marja', (v) => `${v}%`);
    scalar('ton_rate_uzs', 'TON kursi', som);
    scalar('stars_cost_ton', '1 Stars (TON)');
    if (!same(body.discounts, orig.discounts)) out.push(['Chegirmalar', `${orig.discounts.length} ta`, `${body.discounts.length} ta`]);
    for (const m of PREMIUM_MONTHS) {
      if (body.premium_prices[m] !== origPrem(m)) out.push([`Premium ${m} oy`, som(origPrem(m)), som(body.premium_prices[m])]);
    }
    return out;
  }

  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (!editable) return;
    const { body, problem } = collect();
    if (problem) { error.show(problem); return; }
    error.hide();
    const changes = changesOf(body);
    if (!changes.length) { showToast("O'zgarish yo'q"); return; }
    const ok = await runAction({
      button: submit,
      key: 'pricing',
      confirm: {
        title: "Narxlar o'zgartirilsinmi?",
        text: `${summarize(changes, (v) => v)}. Yangi narxlar darhol barcha mijozlarga qo'llanadi.`,
        confirmLabel: 'Ha, saqlash',
        danger: true,
      },
      call: () => api('/api/admin/pricing', { method: 'POST', body }),
      success: 'Narxlar saqlandi',
    });
    if (ok) {
      Object.assign(orig, {
        stars_cost_ton: body.stars_cost_ton, ton_rate_uzs: body.ton_rate_uzs, margin_percent: body.margin_percent,
        star_unit_price_uzs: body.star_unit_price_uzs, discounts: body.discounts,
        premium_prices: body.premium_prices,
      });
    }
  });

  return h('div', { class: 'view pricing' }, pageHead('Narxlar'), form);
}

registerView('pricing', render);
