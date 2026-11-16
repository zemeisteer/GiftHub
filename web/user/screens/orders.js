// Orders: status filter, search, receipt (#/orders/:code), "Yana sotib olish".
// Every amount is a server field; buy again only picks the product and recipient,
// the product screen then prices it from /api/products.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { getProducts, productList, orderTitle, setPrefill } from '../store.js';
import { renderError, renderEmpty, renderLoading, showToast, copyText } from '../../shared/state.js';

// Values of the legacy activeHistoryStatus filter (legacy app before the redesign; database/queries.py list_user_orders).
const FILTERS = [
  ['all', 'Hammasi'],
  ['pending', 'Jarayonda'],
  ['done', 'Bajarildi'],
  ['cancel', 'Bekor qilingan'],
];
const CAT_ICON = { stars: 'star', premium: 'diamond', gift: 'gift' };
const CAT_CLASS = { stars: 'stars', premium: 'premium', gift: 'gifts' };

export function statusInfo(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'completed' || s === 'done') return ['Bajarildi', 'ok'];
  if (s === 'cancelled' || s === 'cancel' || s === 'expired') return ['Bekor qilindi', 'cancel'];
  if (s === 'failed') return ['Xatolik', 'cancel'];
  if (s === 'refunded') return ['Qaytarildi', 'cancel'];
  return ['Jarayonda', 'pending'];
}

const num = (v) => (v !== null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null);
const pad = (n) => String(n).padStart(2, '0');
function formatDate(iso) {
  const d = new Date(String(iso || ''));
  if (Number.isNaN(d.getTime())) return "Noma'lum";
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
const recipientLabel = (r) => {
  const s = String(r ?? '').trim();
  if (!s) return "O'zim";
  return /^\d+$/.test(s) ? s : `@${s.replace(/^@/, '')}`;
};

// Product screen slug for a previous order, or null if it is no longer sold.
function slugFor(details, items) {
  const type = details.product_type;
  const amount = Number(details.amount);
  if (type === 'stars') {
    if (items.some((p) => p.id === `stars-${amount}`)) return `stars-${amount}`;
    return items.some((p) => p.cat === 'stars') && Number.isInteger(amount) && amount > 0 ? 'stars-custom' : null;
  }
  if (type === 'premium') return items.some((p) => p.id === `premium-${amount}`) ? `premium-${amount}` : null;
  if (type === 'gift') {
    const id = `gift-${String(details.item_title ?? '')}`;
    return items.some((p) => p.id === id) ? id : null;
  }
  return null;
}

let againInFlight = null;

// "Yana sotib olish": the server's buy-again details choose the product and recipient.
export function buyAgain(code, onError) {
  if (againInFlight) return againInFlight;
  tg.haptic('light');
  againInFlight = (async () => {
    try {
      const [details, data] = await Promise.all([
        api(`/api/v1/orders/${encodeURIComponent(code)}/buy-again-details`),
        getProducts(),
      ]);
      const slug = slugFor(details || {}, productList(data));
      if (!slug) {
        onError("Bu mahsulot hozir sotuvda yo'q");
        return;
      }
      setPrefill(slug, {
        recipient: details.recipient_username ?? null,
        starsAmount: slug === 'stars-custom' ? Number(details.amount) : null,
      });
      location.hash = `#/product/${encodeURIComponent(slug)}`;
    } catch (err) {
      tg.haptic('error');
      onError(err && err.message);
    }
  })().finally(() => { againInFlight = null; });
  return againInFlight;
}

function notice() {
  const el = h('div', { class: 'notice notice-error', role: 'alert', hidden: true });
  return {
    node: el,
    show(msg) {
      clear(el);
      el.appendChild(h('p', { class: 'notice-text' }, String(msg || "Noma'lum xatolik")));
      el.removeAttribute('hidden');
    },
    hide() { el.setAttribute('hidden', ''); },
  };
}

function orderRow(o, onAgainError) {
  const type = String(o.product_type || '');
  const [label, kind] = statusInfo(o.status);
  const code = String(o.order_code || '');
  return h('div', { class: 'order-row' },
    h('span', { class: `product-icon ic-${CAT_CLASS[type] || 'stars'}` }, icon(CAT_ICON[type] || 'star')),
    h('div', { class: 'order-info' },
      h('span', { class: 'order-title' }, orderTitle(type, o.item_title)),
      h('span', { class: 'order-meta' }, `${o.created_at || ''} · ${code}`)),
    h('div', { class: 'order-right' },
      h('span', { class: 'order-amt' }, num(o.total_price) === null ? '—' : formatSom(o.total_price)),
      h('span', { class: `status status-${kind}` }, label)),
    h('div', { class: 'order-actions' },
      h('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', dataset: { act: 'receipt' },
        onclick: () => { tg.haptic('light'); location.hash = `#/orders/${encodeURIComponent(code)}`; },
      }, icon('receipt'), 'Chek'),
      h('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', dataset: { act: 'again' },
        onclick: () => buyAgain(code, onAgainError),
      }, icon('refresh'), 'Yana sotib olish')));
}

export async function ordersScreen() {
  const myHash = location.hash;
  const active = () => location.hash === myHash;
  let status = 'all';
  let query = '';
  let orders = null;
  let seq = 0;
  const err = notice();
  const list = h('div', { class: 'orders', 'aria-live': 'polite' });

  // Product names for gift orders; the list still renders if products fail.
  getProducts().then(() => { if (orders && active()) renderList(); }).catch(() => {});

  function renderList() {
    clear(list);
    const q = query.trim().toLowerCase();
    const shown = orders.filter((o) => !q
      || String(o.order_code || '').toLowerCase().includes(q)
      || orderTitle(o.product_type, o.item_title).toLowerCase().includes(q)
      || String(o.item_title || '').toLowerCase().includes(q));
    if (!shown.length) {
      list.appendChild(renderEmpty("Buyurtmalar yo'q", q || status !== 'all'
        ? "Ushbu holat bo'yicha hech qanday buyurtma topilmadi"
        : 'Barcha xaridlaringiz holati shu yerda ko\'rinadi'));
      return;
    }
    for (const o of shown) list.appendChild(orderRow(o, (m) => { if (active()) err.show(m); }));
  }

  async function load() {
    const mine = ++seq;
    err.hide();
    clear(list);
    list.appendChild(renderLoading());
    try {
      const res = await api(`/api/orders/history?status=${encodeURIComponent(status)}`);
      if (mine !== seq) return;
      orders = Array.isArray(res) ? res.filter((o) => o && typeof o === 'object') : [];
      renderList();
    } catch (e) {
      if (mine !== seq) return;
      clear(list);
      list.appendChild(renderError(e && e.message, () => load()));
    }
  }

  const chips = FILTERS.map(([key, label]) => h('button', {
    type: 'button', class: 'chip', dataset: { status: key }, 'aria-pressed': key === status ? 'true' : 'false',
    onclick: () => {
      status = key;
      for (const c of chips) c.setAttribute('aria-pressed', c.dataset.status === key ? 'true' : 'false');
      tg.haptic('light');
      load();
    },
  }, label));

  const search = h('input', {
    type: 'search', class: 'search-input', placeholder: "Buyurtma kodi yoki mahsulot",
    'aria-label': 'Buyurtmalarni qidirish', autocomplete: 'off', enterkeyhint: 'search',
    oninput: (e) => { query = e.target.value || ''; if (orders) renderList(); },
  });

  const root = h('div', { class: 'orders-page' },
    h('h1', { class: 'page-title' }, 'Buyurtmalar'),
    h('label', { class: 'search' }, icon('search'), search),
    h('div', { class: 'chips', role: 'group', 'aria-label': 'Holat' }, chips),
    err.node,
    list);
  await load();
  return root;
}

const row = (label, value, cls) => h('div', { class: 'summary-row' }, h('span', null, label), h('span', { class: cls || 'summary-value' }, value));

function receiptText(r, title) {
  const f = r.financials || {};
  return [
    'GiftHub chek',
    `Chek: #${r.receipt_number}`,
    `Mahsulot: ${title}`,
    `Qabul qiluvchi: ${recipientLabel(r.delivery && r.delivery.recipient_username)}`,
    `Summa: ${formatSom(f.total_price_uzs)}`,
    `Holati: ${statusInfo(r.payment && r.payment.status)[0]}`,
    `Sana: ${formatDate(r.paid_at || r.date)}`,
  ].join('\n');
}

export async function receiptScreen({ code } = {}) {
  const myHash = location.hash;
  const res = await api(`/api/v1/orders/${encodeURIComponent(code)}/receipt`);
  const r = res && res.receipt;
  if (!r || typeof r !== 'object') return renderEmpty('Chek topilmadi', null);
  await getProducts().catch(() => null);
  const p = r.product || {};
  const f = r.financials || {};
  const pay = r.payment || {};
  const d = r.delivery || {};
  const title = orderTitle(p.product_type, p.item_title) || 'Raqamli mahsulot';
  const err = notice();
  const discount = num(f.discount_amount_uzs);

  return h('div', { class: 'receipt-page' },
    h('section', { class: 'receipt' },
      h('div', { class: 'receipt-head' },
        h('span', { class: 'state-icon' }, icon('receipt')),
        h('div', null,
          h('h1', { class: 'product-title' }, 'GiftHub chek'),
          h('span', { class: 'order-meta' }, `#${r.receipt_number || code}`))),
      h('div', { class: 'summary' },
        row("To'lov sanasi", formatDate(r.paid_at || r.date)),
        row('Mahsulot', title),
        row('Miqdori', String(num(p.quantity) ?? 1)),
        row('Qabul qiluvchi', recipientLabel(d.recipient_username)),
        num(f.unit_price_uzs) ? row('Dona narxi', formatSom(f.unit_price_uzs)) : null,
        discount ? row('Chegirma', `-${formatSom(discount)}`) : null,
        f.promo_code ? row('Promo-kod', String(f.promo_code)) : null,
        row("To'lov usuli", String(pay.provider || pay.method || 'balans').toUpperCase()),
        row('Holati', statusInfo(pay.status)[0]),
        row('Jami', formatSom(f.total_price_uzs), 'summary-value summary-total')),
      d.tx_hash ? h('p', { class: 'field-hint tx-hash' }, `Fragment TX: ${String(d.tx_hash)}`) : null),
    err.node,
    h('div', { class: 'stack' },
      h('button', {
        type: 'button', class: 'btn btn-secondary btn-block',
        onclick: async () => {
          if (await copyText(receiptText(r, title))) showToast('Nusxa olindi');
          else showToast("Nusxa olib bo'lmadi");
        },
      }, icon('copy'), 'Chekni nusxalash'),
      h('button', {
        type: 'button', class: 'btn btn-primary btn-block',
        onclick: () => buyAgain(String(r.receipt_number || code), (m) => { if (location.hash === myHash) err.show(m); }),
      }, icon('refresh'), 'Yana sotib olish')));
}

