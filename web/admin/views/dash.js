// Bosh sahifa: KPIs -> needs attention -> sales chart (with period) -> top products -> profit table.
// Data: GET /api/admin/stats (ANALYTICS_READ) and GET /api/v1/admin/orders/problematic (ORDERS_READ).
import { h, clear, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView, setBadge } from '../registry.js';
import { barChart } from '../chart.js';
import { can, chips, pageHead, emptyNote, inlineError } from './ui.js';
import { problemRow } from './problems.js';

const PERIODS = [['daily', 'Bugun'], ['weekly', '7 kun'], ['monthly', '30 kun']];
const CHART_SUB = {
  daily: 'Bugun, har 4 soatda',
  weekly: "So'nggi 7 kun",
  monthly: "So'nggi 4 hafta",
};
const SHOWN = 5;

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

function kpi(label, value, note) {
  return h('div', { class: 'kpi' },
    h('div', { class: 'kpi-label' }, label),
    h('div', { class: 'kpi-value' }, value),
    note ? h('div', { class: 'kpi-note' }, note) : null);
}

function attentionSection() {
  const body = h('div', { class: 'attention-body', 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Yuklanmoqda...'));
  const head = h('div', { class: 'section-head' }, h('h2', { class: 'section-title' }, "E'tibor talab qiladi"));
  const root = h('section', { class: 'card attention-card' }, head, body);

  function paint(data) {
    clear(body);
    const orders = Array.isArray(data && data.orders) ? data.orders : [];
    if (!orders.length) {
      body.appendChild(emptyNote("Muammoli buyurtmalar yo'q", "Hammasi joyida."));
      return;
    }
    body.appendChild(h('ul', { class: 'attention-list' }, orders.slice(0, SHOWN).map((o) => problemRow(o, load))));
    if (orders.length > SHOWN) {
      body.appendChild(h('a', { class: 'link-more', href: '#/orders/problems' }, `Barchasini ko'rish (${orders.length})`));
    }
  }

  async function load() {
    try {
      const data = await api('/api/v1/admin/orders/problematic');
      setBadge('orders', data && data.counts && data.counts.total_problematic);
      paint(data);
      const total = num(data && data.counts && data.counts.total_problematic);
      head.querySelector('.count-pill')?.remove();
      if (total) head.appendChild(h('span', { class: 'count-pill' }, String(total)));
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }
  return { root, load };
}

function chartCard(charts) {
  const holder = h('div', { class: 'chart-holder' });
  const sub = h('p', { class: 'muted' });
  let period = 'weekly';
  function paint(period) {
    const series = Array.isArray(charts && charts[period]) ? charts[period] : [];
    sub.textContent = CHART_SUB[period];
    clear(holder);
    if (!series.some((p) => num(p.sales) > 0)) {
      holder.appendChild(emptyNote("Ma'lumotlar mavjud emas"));
      return;
    }
    holder.appendChild(barChart(series.map((p) => ({ label: p.label, value: num(p.sales) })), { height: 120 }));
  }
  // The server returns all three series at once and the KPI cards are not period-based,
  // so this control lives in the chart card and only swaps the chart series.
  const periods = chips(PERIODS, period, (p) => { period = p; paint(p); }, 'chips period');
  const root = h('section', { class: 'card chart-card' },
    h('h2', { class: 'section-title' }, 'Savdo grafigi'),
    h('div', { class: 'period-row' }, h('span', { class: 'field-label' }, 'Grafik davri'), periods),
    sub, holder);
  paint(period);
  return { root };
}

function topProducts(breakdown) {
  const rows = (Array.isArray(breakdown) ? breakdown : []).slice().sort((a, b) => num(b.sales) - num(a.sales));
  const max = Math.max(1, ...rows.map((r) => num(r.sales)));
  return h('section', { class: 'card top-products' },
    h('h2', { class: 'section-title' }, 'Top mahsulotlar'),
    rows.length
      ? h('ol', { class: 'top-list' }, rows.map((r) => h('li', { class: 'top-item' },
        h('div', { class: 'top-row' }, h('span', null, r.name), h('b', null, formatSom(r.sales))),
        h('div', { class: 'top-bar' }, h('span', { style: { width: `${Math.round((num(r.sales) / max) * 100)}%` } })))))
      : emptyNote("Ma'lumotlar mavjud emas"));
}

function profitTable(breakdown) {
  const rows = Array.isArray(breakdown) ? breakdown : [];
  return h('section', { class: 'card profit-table' },
    h('h2', { class: 'section-title' }, 'Foyda jadvali'),
    h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Yo\'nalish', 'Savdo', 'Tannarx', 'Foyda'].map((t) => h('th', null, t)))),
      h('tbody', null, rows.map((r) => h('tr', null,
        h('td', { 'data-label': "Yo'nalish" }, h('b', null, r.name)),
        h('td', { 'data-label': 'Savdo' }, formatSom(r.sales)),
        h('td', { 'data-label': 'Tannarx' }, formatSom(r.cost)),
        h('td', { 'data-label': 'Foyda', class: 'profit' }, formatSom(r.profit)))))));
}

async function render() {
  // A failing stats request rejects so the router shows its retry state.
  const stats = (await api('/api/admin/stats')) || {};
  const chart = chartCard(stats.charts);
  const root = h('div', { class: 'view dash' },
    pageHead('Bosh sahifa'),
    h('div', { class: 'kpis' },
      kpi('Yangi foydalanuvchilar', String(num(stats.new_users_week)), 'Oxirgi 7 kun'),
      kpi('Savdo', formatSom(stats.sales_total), 'Jami'),
      kpi('Foyda', formatSom(stats.profit_total), 'Jami'),
      kpi('Referal savdolar', `${num(stats.ref_sales_count)} ta`, 'Jami')));
  if (can('ORDERS_READ')) {
    const att = attentionSection();
    root.appendChild(att.root);
    // Not awaited: KPIs and the chart show right away; the section has its own loading/error state.
    att.load();
  }
  root.appendChild(chart.root);
  root.appendChild(topProducts(stats.breakdown));
  root.appendChild(profitTable(stats.breakdown));
  return root;
}

registerView('dash', render);
