// Home screen (B · store style): balance, search, category chips, product grid.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { tg } from '../../shared/tg.js';
import { appState, cachedProducts, getProducts, productList } from '../store.js';
import { renderError, renderEmpty, skeletonCards } from '../../shared/state.js';

const CATEGORIES = [
  ['all', 'Hammasi'],
  ['stars', 'Stars'],
  ['premium', 'Premium'],
  ['gifts', "Sovg'alar"],
];

// The slug <-> product mapping lives in store.js so product.js resolves the same ids.
export { productList };

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
