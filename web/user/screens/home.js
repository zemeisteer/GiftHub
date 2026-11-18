// Home screen (D · colourful tiles): greeting + balance pill, category tiles, product shelf.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { tg } from '../../shared/tg.js';
import { appState, cachedProducts, getProducts, productList } from '../store.js';
import { renderError, renderEmpty, skeletonCards } from '../../shared/state.js';

// The slug <-> product mapping lives in store.js so product.js resolves the same ids.
export { productList };

const CAT_ICON = { stars: 'star', premium: 'diamond', gifts: 'gift' };
const SHELF_TITLE = { all: 'Tezkor xarid', stars: 'Telegram Stars', premium: 'Telegram Premium', gifts: "Sovg'alar" };
// [category, label, extra class]; Stars is the large tile on the left.
const TILES = [
  ['stars', 'Stars', 'tile-big'],
  ['premium', 'Premium', ''],
  ['gifts', "Sovg'alar", ''],
];

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

// Lowest price of a category, straight from server prices (nothing is computed for checkout).
function fromPrice(items, cat) {
  if (!items) return '';
  const prices = items.filter((p) => p.cat === cat && Number.isFinite(p.price) && p.price > 0).map((p) => p.price);
  return prices.length ? `${formatSom(Math.min(...prices))} dan` : '';
}

export async function homeScreen() {
  let cat = 'all';
  let items = null;

  const grid = h('div', { class: 'grid', 'aria-live': 'polite' });
  const results = h('div', { class: 'results' }, grid);
  const shelfTitle = h('h2', { class: 'shelf-title' }, SHELF_TITLE.all);
  const resetBtn = h('button', {
    type: 'button',
    class: 'shelf-reset',
    hidden: true,
    onclick: () => select('all'),
  }, 'Hammasi');
  const shelf = h('section', { class: 'shelf' }, h('div', { class: 'shelf-head' }, shelfTitle, resetBtn), results);

  const subs = {};
  const tiles = TILES.map(([key, label, extra]) => {
    subs[key] = h('span', { class: 'tile-sub' });
    return h('button', {
      type: 'button',
      class: `tile tile-${key} ${extra}`.trim(),
      'aria-pressed': 'false',
      dataset: { cat: key },
      onclick: () => {
        tg.haptic('light');
        select(cat === key ? 'all' : key);
        shelf.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      },
    },
    h('span', { class: 'tile-icon' }, icon(CAT_ICON[key])),
    h('span', { class: 'tile-text' }, h('span', { class: 'tile-name' }, label), subs[key]));
  });

  const refTile = h('button', {
    type: 'button',
    class: 'tile tile-ref tile-wide',
    onclick: () => { tg.haptic('light'); location.hash = '#/referral'; },
  },
  h('span', { class: 'tile-icon' }, icon('users')),
  h('span', { class: 'tile-text' }, h('span', { class: 'tile-name' }, "Do'stni taklif qil"), h('span', { class: 'tile-sub' }, 'Har bir xariddan bonus')),
  h('span', { class: 'tile-arrow' }, icon('chevron-right')));

  function paintSubs() {
    for (const [key] of TILES) subs[key].textContent = fromPrice(items, key);
  }

  function select(next) {
    cat = next;
    for (const t of tiles) t.setAttribute('aria-pressed', t.dataset.cat === cat ? 'true' : 'false');
    shelfTitle.textContent = SHELF_TITLE[cat];
    if (cat === 'all') resetBtn.setAttribute('hidden', '');
    else resetBtn.removeAttribute('hidden');
    renderGrid();
  }

  function renderGrid() {
    clear(results);
    if (!items) {
      clear(grid);
      grid.append(...skeletonCards(6));
      results.appendChild(grid);
      return;
    }
    const shown = items.filter((p) => cat === 'all' || p.cat === cat);
    clear(grid);
    if (!shown.length) {
      results.appendChild(renderEmpty('Hozircha mahsulot yo\'q', "Boshqa toifani tanlab ko'ring"));
      return;
    }
    for (const p of shown) grid.appendChild(productCard(p));
    results.appendChild(grid);
  }

  const name = appState.user && appState.user.first_name;
  const root = h('div', { class: 'home' },
    h('header', { class: 'home-head' },
      h('div', { class: 'greet' },
        h('span', { class: 'greet-hi' }, name ? `Salom, ${name}!` : 'Salom!'),
        h('span', { class: 'greet-brand' }, 'GiftHub')),
      h('button', {
        type: 'button',
        class: 'balance-pill',
        'aria-label': `Balans ${formatSom(appState.balance)}, to'ldirish`,
        onclick: () => { tg.haptic('light'); location.hash = '#/topup'; },
      }, h('span', { class: 'balance-value' }, formatSom(appState.balance)), icon('plus'))),
    h('div', { class: 'tiles', role: 'group', 'aria-label': 'Toifalar' }, tiles, refTile),
    shelf);

  function load(force) {
    items = null;
    renderGrid();
    getProducts({ force }).then((data) => { items = productList(data); paintSubs(); renderGrid(); }).catch((err) => {
      clear(results);
      results.appendChild(renderError(err && err.message, () => load(true)));
    });
  }

  const fresh = cachedProducts();
  if (fresh) {
    items = productList(fresh);
    paintSubs();
    renderGrid();
  } else {
    load(false);
  }
  return root;
}
