// Foydalanuvchilar: search + paging over GET /api/admin/users (USERS_READ).
// Names and usernames are user-controlled: they only ever reach the DOM as text through h().
import { h, clear, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { debounce, pager, pageHead, emptyNote, inlineError, badge } from './ui.js';

const PAGE = 20;

function table(rows) {
  const heads = ['Foydalanuvchi', 'Rol', 'Balans', 'Buyurtmalar', 'Sarflagan', 'Referallar', "Qo'shilgan"];
  return h('table', { class: 'table users-table' },
    h('thead', null, h('tr', null, heads.map((t) => h('th', null, t)))),
    h('tbody', null, rows.map((u) => h('tr', null,
      h('td', { 'data-label': 'Foydalanuvchi' },
        h('b', null, u.first_name || ''), ' ', h('span', { class: 'muted' }, `(${u.username})`)),
      h('td', { 'data-label': 'Rol' }, badge(String(u.role || ''), u.role === 'user' ? 'pending' : 'ok')),
      h('td', { 'data-label': 'Balans' }, h('b', null, formatSom(u.balance))),
      h('td', { 'data-label': 'Buyurtmalar' }, `${Number(u.orders_count) || 0} ta`),
      h('td', { 'data-label': 'Sarflagan' }, formatSom(u.total_spent)),
      h('td', { 'data-label': 'Referallar' }, `${Number(u.referrals_count) || 0} ta`),
      h('td', { 'data-label': "Qo'shilgan" }, u.created_at)))));
}

async function render() {
  const state = { search: '', offset: 0 };
  let seq = 0;
  const body = h('div', { class: 'list-body', 'aria-live': 'polite' });

  async function load() {
    const mine = ++seq;
    const params = new URLSearchParams();
    if (state.search) params.set('search', state.search);
    params.set('limit', String(PAGE + 1)); // the extra row tells us whether a next page exists
    params.set('offset', String(state.offset));
    let rows;
    try {
      rows = await api(`/api/admin/users?${params}`);
    } catch (err) {
      if (mine !== seq) return;
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
      return;
    }
    if (mine !== seq) return;
    rows = Array.isArray(rows) ? rows : [];
    clear(body);
    if (!rows.length) body.appendChild(emptyNote('Foydalanuvchi topilmadi'));
    else body.appendChild(table(rows.slice(0, PAGE)));
    const p = pager({ offset: state.offset, hasNext: rows.length > PAGE, onPrev: prev, onNext: next });
    if (p) body.appendChild(p);
  }
  function prev() { state.offset = Math.max(0, state.offset - PAGE); load(); }
  function next() { state.offset += PAGE; load(); }

  const search = h('input', {
    type: 'search', class: 'input', placeholder: 'Ism, @username yoki ID', 'aria-label': 'Qidirish', autocomplete: 'off',
  });
  search.addEventListener('input', debounce(() => {
    state.search = search.value.trim();
    state.offset = 0;
    load();
  }));

  const root = h('div', { class: 'view users' },
    pageHead('Foydalanuvchilar'),
    h('div', { class: 'filters' }, search),
    body);
  await load();
  return root;
}

registerView('users', render);
