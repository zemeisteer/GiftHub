// Problem orders: shared row (dashboard + panel) and the full panel at #/orders/problems.
// GET /api/v1/admin/orders/problematic[?category=&limit=] (ORDERS_READ); actions need ORDERS_UPDATE.
import { h, clear, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { setBadge } from '../registry.js';
import {
  can, chips, pager, runAction, pageHead, emptyNote, inlineError, badge, orderStatus, formatDate,
} from './ui.js';
import { openTimeline } from './timeline.js';

// Category values and count fields are the backend's (router.py get_problem_orders).
export const CATEGORIES = [
  ['', 'Hammasi', 'total_problematic'],
  ['paid_not_fulfilled', "To'langan, yetkazilmagan", 'paid_not_fulfilled'],
  ['stuck_processing', 'Qotib qolgan', 'stuck_processing'],
  ['payment_mismatch', "To'lov mos emas", 'payment_mismatch'],
  ['failed_fulfillment', 'Yetkazish xatosi', 'failed_fulfillment'],
  ['pending_refund', 'Qaytarish kutilmoqda', 'pending_refund'],
];
const PAGE = 10;
const FETCH_LIMIT = 200; // the endpoint has a limit but no offset, so paging is done client-side

export const orderLockKey = (id) => `order:${id}`;

export function problemRow(o, reload) {
  const code = o.order_code || `GH-${String(o.id).padStart(6, '0')}`;
  const reason = o.problem_detail || o.fulfillment_error || "Noma'lum sabab";
  const [statusLabel, tone] = orderStatus(o.status);
  const actions = [];
  if (can('ORDERS_UPDATE')) {
    const retry = h('button', { type: 'button', class: 'btn btn-secondary' }, 'Qayta yuborish');
    retry.addEventListener('click', () => runAction({
      button: retry,
      key: orderLockKey(o.id),
      confirm: {
        title: 'Qayta yuborilsinmi?',
        text: `${code} buyurtmasi yetkazib berishga qayta yuboriladi.`,
        confirmLabel: 'Yuborish',
        input: { label: 'Sabab', required: true, minLength: 5, defaultValue: "Admin paneldan qo'lda qayta urinish buyurildi" },
      },
      call: async (reasonText) => {
        const data = await api(`/api/v1/admin/orders/${encodeURIComponent(o.id)}/retry-fulfillment`, {
          method: 'POST', body: { reason: reasonText },
        });
        if (!data || !data.success) throw new Error((data && data.result && data.result.error) || 'Qayta urinishda xatolik');
        return data;
      },
      success: 'Qayta yetkazish boshlandi',
    }).then((ok) => { if (ok) reload(); }));
    const manual = h('button', { type: 'button', class: 'btn btn-secondary' }, "Qo'lda bajarildi");
    manual.addEventListener('click', () => runAction({
      button: manual,
      key: orderLockKey(o.id),
      confirm: {
        title: "Qo'lda bajarildi deb belgilansinmi?",
        text: `${code} buyurtmasi yetkazilgan deb belgilanadi va mijozga yetkazilgan hisoblanadi.`,
        confirmLabel: 'Bajarildi deb belgilash',
        danger: true,
        input: { label: 'Sabab', required: true, minLength: 5, defaultValue: "Fragment orqali qo'lda yuborildi" },
      },
      call: (reasonText) => api(`/api/v1/admin/orders/${encodeURIComponent(o.id)}/manual-fulfill`, {
        method: 'POST', body: { reason: reasonText },
      }),
      success: 'Buyurtma yakunlandi',
    }).then((ok) => { if (ok) reload(); }));
    actions.push(retry, manual);
  }
  actions.push(h('button', { type: 'button', class: 'btn btn-secondary', onclick: () => openTimeline(code) }, 'Tarix'));
  return h('li', { class: 'attention' },
    h('div', { class: 'attention-main' },
      h('div', { class: 'attention-top' },
        h('b', { class: 'mono' }, code),
        h('span', { class: 'muted' }, formatDate(o.created_at))),
      h('div', null, `${o.item_title || o.product_type || ''}${o.amount ? ` × ${o.amount}` : ''}`),
      h('div', { class: 'muted' }, `${o.recipient_username ? `@${String(o.recipient_username).replace(/^@/, '')}` : `ID ${o.user_id}`} · ${formatSom(o.total_price)}`),
      h('div', { class: 'attention-meta' },
        badge(statusLabel, tone),
        h('span', { class: 'muted small' }, `Yetkazish: ${o.fulfillment_status || 'kutilmoqda'}`),
        h('span', { class: 'muted small' }, `To'lov: ${o.payment_method || 'balance'}`)),
      h('div', { class: 'attention-reason' }, reason)),
    h('div', { class: 'attention-actions' }, actions));
}

export async function renderProblems() {
  const state = { category: '', page: 0 };
  let seq = 0;
  let orders = [];
  const body = h('div', { class: 'list-body', 'aria-live': 'polite' });
  const tabHost = h('div', { class: 'problem-tabs' });
  let tabs = null;

  function paintTabs(counts) {
    const opts = CATEGORIES.map(([val, label, field]) => [val, `${label} (${Number(counts && counts[field]) || 0})`]);
    tabs = chips(opts, state.category, (v) => { state.category = v; state.page = 0; load(); }, 'chips');
    clear(tabHost);
    tabHost.appendChild(tabs);
  }
  function paintList() {
    clear(body);
    if (!orders.length) { body.appendChild(emptyNote("Ushbu toifada muammoli buyurtmalar yo'q")); return; }
    const slice = orders.slice(state.page * PAGE, (state.page + 1) * PAGE);
    body.appendChild(h('ul', { class: 'attention-list card' }, slice.map((o) => problemRow(o, load))));
    const p = pager({
      offset: state.page * PAGE,
      hasNext: (state.page + 1) * PAGE < orders.length,
      onPrev: () => { state.page -= 1; paintList(); },
      onNext: () => { state.page += 1; paintList(); },
    });
    if (p) body.appendChild(p);
  }
  async function load() {
    const mine = ++seq;
    const q = new URLSearchParams();
    if (state.category) q.set('category', state.category);
    q.set('limit', String(FETCH_LIMIT));
    try {
      const data = await api(`/api/v1/admin/orders/problematic?${q}`);
      if (mine !== seq) return;
      orders = Array.isArray(data && data.orders) ? data.orders : [];
      setBadge('orders', data && data.counts && data.counts.total_problematic);
      paintTabs(data && data.counts);
      state.page = Math.min(state.page, Math.max(0, Math.ceil(orders.length / PAGE) - 1));
      paintList();
    } catch (err) {
      if (mine !== seq) return;
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }

  const root = h('div', { class: 'view problems' },
    pageHead('Muammoli buyurtmalar', h('a', { class: 'btn btn-secondary', href: '#/orders' }, 'Barcha buyurtmalar')),
    tabHost,
    body);
  await load();
  return root;
}
