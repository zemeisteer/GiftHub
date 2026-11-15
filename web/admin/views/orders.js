// Buyurtmalar: search, status/type filters, paging, CSV export and the legacy per-order actions.
// GET /api/admin/orders (ORDERS_READ); actions need ORDERS_UPDATE (server-enforced).
import { h, clear, formatSom, safeUrl, icon } from '../../shared/dom.js';
import { api, apiBlob } from '../../shared/api.js';
import { registerView } from '../registry.js';
import {
  can, debounce, runAction, chips, pager, pageHead, emptyNote, inlineError, badge, orderStatus, saveBlob, showToast, formatDate,
} from './ui.js';
import { renderProblems, orderLockKey } from './problems.js';
import { openTimeline } from './timeline.js';

const PAGE = 20;
// Values are the legacy ones; the server maps done -> completed and cancel -> cancelled.
const STATUS = [['all', 'Hammasi'], ['pending', 'Kutilmoqda'], ['done', 'Bajarildi'], ['cancel', 'Bekor']];
const TYPES = [['all', 'Barchasi'], ['stars', 'Stars'], ['premium', 'Premium'], ['gift', "Sovg'a"]];
const CLOSED = new Set(['cancelled', 'cancel', 'refunded', 'expired']);

function fulfillmentCell(o) {
  const f = o.fulfillment_status;
  const parts = [];
  if (f === 'fulfilled') parts.push(badge('Yetkazildi', 'ok'));
  else if (f === 'processing') parts.push(badge('Yuborilmoqda', 'pending'));
  else if (f === 'failed') parts.push(badge('Xato', 'cancel'));
  else parts.push(badge('Kutilmoqda', 'pending'));
  if (f === 'failed' && o.fulfillment_error) parts.push(h('div', { class: 'muted small' }, String(o.fulfillment_error)));
  if (f === 'fulfilled' && o.fragment_tx_hash) {
    const href = safeUrl(`https://tonscan.org/tx/${encodeURIComponent(String(o.fragment_tx_hash))}`);
    if (href) parts.push(h('div', { class: 'small' }, h('a', { class: 'link', href, target: '_blank', rel: 'noopener noreferrer' }, 'TON chek')));
  }
  return parts;
}

function actionButton(label, o, _name, spec, reload, cls = 'btn btn-secondary btn-sm') {
  const b = h('button', { type: 'button', class: cls }, label);
  b.addEventListener('click', () => runAction({ button: b, key: orderLockKey(o.id), ...spec }).then((ok) => { if (ok) reload(); }));
  return b;
}

function actionsCell(o, reload) {
  const history = h('button', { type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => openTimeline(o.order_code) }, 'Tarix');
  if (!can('ORDERS_UPDATE')) return [history];
  const status = String(o.status || '').toLowerCase();
  const closed = CLOSED.has(status);
  const fulfilled = o.fulfillment_status === 'fulfilled';
  const code = o.order_code;
  const out = [history];
  if (!fulfilled && !closed) {
    out.push(actionButton('Fragment', o, 'fragment', {
      confirm: { title: 'Fragment orqali yetkazilsinmi?', text: `${code} buyurtmasi Fragment orqali darhol yetkaziladi.`, confirmLabel: 'Yetkazish' },
      call: async () => {
        const data = await api(`/api/admin/orders/${encodeURIComponent(o.id)}/fulfill-fragment`, { method: 'POST' });
        if (data && data.success && data.fulfilled) return data;
        if (data && data.mode === 'waiting_payment') return data;
        throw new Error((data && data.error) || 'Fragment yetkazishda xatolik');
      },
      success: (data) => (data.fulfilled ? 'Buyurtma Fragment orqali yetkazildi' : "Tonkeeper to'lov havolasi tayyor"),
    }, reload, 'btn btn-primary btn-sm'));
    const tk = o.fragment_payload && safeUrl(String(o.fragment_payload));
    if (tk && tk.startsWith('https://')) {
      out.push(h('a', { class: 'btn btn-secondary btn-sm', href: tk, target: '_blank', rel: 'noopener noreferrer' }, 'Tonkeeper'));
    }
    out.push(actionButton('Yetkazildi', o, 'fulfilled', {
      confirm: { title: 'Yetkazildi deb belgilansinmi?', text: `${code} mijozga yetkazilgan hisoblanadi.`, confirmLabel: 'Belgilash' },
      call: () => api(`/api/admin/orders/${encodeURIComponent(o.id)}/mark-fulfilled`, { method: 'POST' }),
      success: 'Buyurtma yetkazildi deb belgilandi',
    }, reload));
  }
  if (!closed && status !== 'completed' && status !== 'done' && fulfilled) {
    out.push(actionButton('Yakunlash', o, 'done', {
      confirm: { title: 'Buyurtma yakunlansinmi?', text: `${code} holati "Bajarildi" ga o'zgaradi.`, confirmLabel: 'Yakunlash' },
      call: () => api(`/api/admin/orders/${encodeURIComponent(o.id)}/status`, { method: 'POST', body: { status: 'done' } }),
      success: 'Buyurtma holati yangilandi',
    }, reload));
  }
  if (!closed) {
    out.push(actionButton('Qaytarish', o, 'cancel', {
      confirm: {
        title: 'Buyurtma bekor qilinsinmi?',
        text: `${code} bekor qilinadi va mablag' mijozga qaytariladi.`,
        confirmLabel: 'Bekor qilish va qaytarish',
        danger: true,
      },
      call: () => api(`/api/admin/orders/${encodeURIComponent(o.id)}/status`, { method: 'POST', body: { status: 'cancel' } }),
      success: 'Buyurtma bekor qilindi',
    }, reload, 'btn btn-danger btn-sm'));
  }
  return out;
}

function table(rows, reload) {
  const showActions = true; // "Tarix" is available to every reader; the other actions need ORDERS_UPDATE
  const heads = ['Kod', 'Mijoz', 'Qabul qiluvchi', 'Mahsulot', 'Summa', 'Sana', 'Holat', 'Yetkazish'];
  if (showActions) heads.push('Amallar');
  return h('table', { class: 'table orders-table' },
    h('thead', null, h('tr', null, heads.map((t) => h('th', null, t)))),
    h('tbody', null, rows.map((o) => {
      const [label, tone] = orderStatus(o.status);
      const recipient = o.recipient_username ? `@${String(o.recipient_username).replace(/^@/, '')}` : o.username;
      return h('tr', null,
        h('td', { 'data-label': 'Kod' }, h('b', { class: 'mono' }, o.order_code)),
        h('td', { 'data-label': 'Mijoz' }, o.username),
        h('td', { 'data-label': 'Qabul qiluvchi' }, recipient),
        h('td', { 'data-label': 'Mahsulot' }, `${o.item_title || ''}${o.amount ? ` × ${o.amount}` : ''}`),
        h('td', { 'data-label': 'Summa' }, h('b', null, formatSom(o.total_price))),
        h('td', { 'data-label': 'Sana' }, formatDate(o.created_at)),
        h('td', { 'data-label': 'Holat' }, badge(label, tone)),
        h('td', { 'data-label': 'Yetkazish' }, fulfillmentCell(o)),
        showActions ? h('td', { 'data-label': 'Amallar', class: 'actions' }, h('div', { class: 'row-actions' }, actionsCell(o, reload))) : null);
    })));
}

async function render(params = {}) {
  if (params.sub === 'problems') return renderProblems();
  const state = { search: '', status: 'all', type: 'all', offset: 0 };
  let seq = 0;
  const body = h('div', { class: 'list-body', 'aria-live': 'polite' });

  async function load() {
    const mine = ++seq;
    const params = new URLSearchParams();
    if (state.search) params.set('search', state.search);
    if (state.status !== 'all') params.set('status', state.status);
    if (state.type !== 'all') params.set('product_type', state.type);
    params.set('limit', String(PAGE + 1)); // one extra row tells us whether a next page exists
    params.set('offset', String(state.offset));
    let rows;
    try {
      rows = await api(`/api/admin/orders?${params}`);
    } catch (err) {
      if (mine !== seq) return;
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
      return;
    }
    if (mine !== seq) return;
    rows = Array.isArray(rows) ? rows : [];
    clear(body);
    if (!rows.length) {
      body.appendChild(emptyNote('Buyurtmalar topilmadi'));
      const p = pager({ offset: state.offset, hasNext: false, onPrev: prev, onNext: next });
      if (p) body.appendChild(p);
      return;
    }
    body.appendChild(table(rows.slice(0, PAGE), load));
    const p = pager({ offset: state.offset, hasNext: rows.length > PAGE, onPrev: prev, onNext: next });
    if (p) body.appendChild(p);
  }
  function prev() { state.offset = Math.max(0, state.offset - PAGE); load(); }
  function next() { state.offset += PAGE; load(); }
  const refilter = (patch) => { Object.assign(state, patch, { offset: 0 }); load(); };

  let exporting = false;
  const exportBtn = h('button', { type: 'button', class: 'btn btn-secondary' }, icon('receipt'), 'Eksport');
  exportBtn.addEventListener('click', async () => {
    if (exporting) return;
    exporting = true;
    exportBtn.setAttribute('disabled', '');
    try {
      // The server exports the latest 1000 orders; it has no filter parameters.
      saveBlob(await apiBlob('/api/admin/export/orders.csv'), 'gifthub_orders.csv');
    } catch (err) {
      showToast((err && err.message) || 'Eksportda xatolik');
    } finally {
      exporting = false;
      exportBtn.removeAttribute('disabled');
    }
  });

  const search = h('input', {
    type: 'search', class: 'input', placeholder: 'Kod, mahsulot yoki ID', 'aria-label': 'Qidirish', autocomplete: 'off',
  });
  search.addEventListener('input', debounce(() => refilter({ search: search.value.trim() })));

  const root = h('div', { class: 'view orders' },
    pageHead('Buyurtmalar', h('a', { class: 'btn btn-secondary', href: '#/orders/problems' }, 'Muammoli buyurtmalar'), exportBtn),
    h('div', { class: 'filters' },
      search,
      chips(STATUS, 'all', (v) => refilter({ status: v })),
      chips(TYPES, 'all', (v) => refilter({ type: v }))),
    body);
  await load();
  return root;
}

registerView('orders', render);
