// User Web App shell: boot, shared state, bottom nav and routes.
import { h, clear, icon } from '../shared/dom.js';
import { api } from '../shared/api.js';
import { tg } from '../shared/tg.js';
import { createRouter } from '../shared/router.js';
import { renderLoading, renderError, renderEmpty } from './screens/state.js';
import { homeScreen } from './screens/home.js';
import { appState, getProducts } from './store.js';

export { appState, getProducts, cachedProducts } from './store.js';

const TABS = [
  ['home', '#/', 'home', 'Asosiy'],
  ['orders', '#/orders', 'receipt', 'Buyurtmalar'],
  ['referral', '#/referral', 'users', 'Referal'],
  ['profile', '#/profile', 'user', 'Profil'],
];

export function bottomNav(active) {
  return h('div', { class: 'bottom-nav-inner' }, TABS.map(([key, hash, ic, label]) => h('button', {
    type: 'button',
    class: key === active ? 'nav-item active' : 'nav-item',
    'aria-current': key === active ? 'page' : null,
    onclick: () => {
      if (key !== active) tg.haptic('light');
      location.hash = hash;
    },
  }, icon(ic), h('span', { class: 'nav-label' }, label))));
}

const byId = (id) => document.getElementById(id);

function setNav(active) {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);
  nav.appendChild(bottomNav(active));
}

function comingSoon() {
  return renderEmpty('Tez orada', "Bu bo'lim tez orada ishga tushadi");
}

// Tab screens show the nav; sub-screens also get Telegram's back button.
const tab = (key, handler) => async (params) => {
  setNav(key);
  tg.backButton(null);
  return handler(params);
};
const sub = (handler) => async (params) => {
  setNav('home');
  tg.backButton(() => { location.hash = '#/'; });
  return handler(params);
};

// Non-home screens are dynamic import() modules once they exist (Tasks 6-7).
const routes = {
  '#/': tab('home', () => homeScreen()),
  '#/product/:id': sub(comingSoon),
  '#/topup': sub(comingSoon),
  '#/orders': tab('orders', comingSoon),
  '#/referral': tab('referral', comingSoon),
  '#/profile': tab('profile', comingSoon),
};

function renderOpenInBot() {
  return h('div', { class: 'state state-full' },
    h('div', { class: 'state-icon' }, icon('telegram')),
    h('p', { class: 'state-title' }, 'Ilovani @gifthubuzbot ichida oching'),
    h('p', { class: 'state-text' }, "GiftHub faqat Telegram ichida ishlaydi."));
}

async function loadAndStart(outlet) {
  clear(outlet);
  outlet.appendChild(renderLoading());
  let me;
  try {
    [me] = await Promise.all([api('/api/user/me'), getProducts({ force: true })]);
  } catch (err) {
    clear(outlet);
    outlet.appendChild(renderError(err && err.message, () => loadAndStart(outlet)));
    return;
  }
  appState.user = me || null;
  appState.balance = Number(me && me.balance) || 0;
  const router = createRouter(routes, outlet, {
    onError: (err) => renderError(err && err.message, () => router.go(location.hash || '#/')),
  });
  await router.start();
}

export async function boot() {
  const outlet = byId('outlet') || document.body;
  const nav = byId('nav');
  try {
    tg.ready();
    tg.applyTheme(document.documentElement);
    clear(outlet);
    if (nav) clear(nav);
  } catch (err) {
    // Never leave a blank screen: show the error with a retry.
    clear(outlet);
    outlet.appendChild(renderError(err && err.message, () => { boot(); }));
    return;
  }
  if (!tg.inTelegram) {
    outlet.appendChild(renderOpenInBot());
    return;
  }
  await loadAndStart(outlet);
}

if (!globalThis.__GIFTHUB_TEST__) {
  boot().catch((e) => globalThis.console?.error(e));
}
