// Home screen (B · store style): balance, search, category chips, product grid.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { tg } from '../../shared/tg.js';
import { appState, cachedProducts, getProducts } from '../store.js';
import { renderError, renderEmpty, skeletonCards } from './state.js';

const CATEGORIES = [
  ['all', 'Hammasi'],
  ['stars', 'Stars'],
  ['premium', 'Premium'],
  ['gifts', "Sovg'alar"],
];

const price = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);

// Flattens the /api/products response into one list of cards.
export function productList(data) {
  const out = [];
  const d = data || {};
  for (const p of Array.isArray(d.stars_packages) ? d.stars_packages : []) {
    if (price(p.price_uzs) === null || !Number.isFinite(Number(p.amount))) continue;
    out.push({ id: `stars-${Number(p.amount)}`, cat: 'stars', name: `${Number(p.amount)} Stars`, price: price(p.price_uzs), discount: Number(p.discount_pct) || 0 });
  }
  for (const p of Array.isArray(d.premium_packages) ? d.premium_packages : []) {
    if (price(p.price_uzs) === null || !Number.isFinite(Number(p.months))) continue;
    out.push({ id: `premium-${Number(p.months)}`, cat: 'premium', name: String(p.name || `Premium — ${p.months} oy`), price: price(p.price_uzs), discount: 0 });
  }
  for (const g of Array.isArray(d.gifts) ? d.gifts : []) {
    if (price(g.price_uzs) === null || g.id === undefined || g.id === null) continue;
    const emoji = typeof g.icon === 'string' && g.icon.length <= 8 ? g.icon : null;
    out.push({ id: `gift-${String(g.id)}`, cat: 'gifts', name: String(g.name || "Sovg'a"), price: price(g.price_uzs), discount: 0, emoji });
  }
  return out;
}

const CAT_ICON = { stars: 'star', premium: 'diamond', gifts: 'gift' };

function productCard(p) {
  return h('button', {
    type: 'button',
    class: 'product-card',
    onclick: () => { tg.haptic('light'); location.hash = `#/product/${encodeURIComponent(p.id)}`; },
  },
  h('span', { class: `product-icon ic-${p.cat}` }, p.emoji ? h('span', { class: 'emoji' }, p.emoji) : icon(CAT_ICON[p.cat])),
  p.discount > 0 ? h('span', { class: 'badge' }, `-${p.discount}%`) : null,
  h('span', { class: 'product-name' }, p.name),
  h('span', { class: 'product-price' }, formatSom(p.price)));
}

export async function homeScreen() {
  let cat = 'all';
  let query = '';
  let items = null;

  const grid = h('div', { class: 'grid', 'aria-live': 'polite' });
  const results = h('div', { class: 'results' }, grid);

  function renderGrid() {
    clear(results);
    if (!items) {
      clear(grid);
      grid.append(...skeletonCards(6));
      results.appendChild(grid);
      return;
    }
    const q = query.trim().toLowerCase();
    const shown = items.filter((p) => (cat === 'all' || p.cat === cat) && (!q || p.name.toLowerCase().includes(q)));
    clear(grid);
    if (!shown.length) {
      results.appendChild(renderEmpty('Hech narsa topilmadi', "Boshqa so'z yoki toifani tanlab ko'ring"));
      return;
    }
    for (const p of shown) grid.appendChild(productCard(p));
    results.appendChild(grid);
  }

  const chips = CATEGORIES.map(([key, label]) => h('button', {
    type: 'button',
    class: 'chip',
    'aria-pressed': key === cat ? 'true' : 'false',
    dataset: { cat: key },
    onclick: () => {
      cat = key;
      for (const c of chips) c.setAttribute('aria-pressed', c.dataset.cat === cat ? 'true' : 'false');
      tg.haptic('light');
      renderGrid();
    },
  }, label));

  const search = h('input', {
    type: 'search',
    class: 'search-input',
    placeholder: 'Mahsulot qidirish',
    'aria-label': 'Mahsulot qidirish',
    autocomplete: 'off',
    enterkeyhint: 'search',
    oninput: (e) => { query = e.target.value || ''; renderGrid(); },
  });

  const root = h('div', { class: 'home' },
    h('section', { class: 'balance-card' },
      h('div', { class: 'balance-info' },
        h('span', { class: 'balance-label' }, 'Balansingiz'),
        h('span', { class: 'balance-value' }, formatSom(appState.balance))),
      h('button', { type: 'button', class: 'btn btn-primary btn-topup', onclick: () => { location.hash = '#/topup'; } }, icon('plus'), "To'ldirish")),
    h('label', { class: 'search' }, icon('search'), search),
    h('div', { class: 'chips', role: 'group', 'aria-label': 'Toifalar' }, chips),
    results);

  function load(force) {
    items = null;
    renderGrid();
    getProducts({ force }).then((data) => { items = productList(data); renderGrid(); }).catch((err) => {
      clear(results);
      results.appendChild(renderError(err && err.message, () => load(true)));
    });
  }

  const fresh = cachedProducts();
  if (fresh) {
    items = productList(fresh);
    renderGrid();
  } else {
    load(false);
  }
  return root;
}
