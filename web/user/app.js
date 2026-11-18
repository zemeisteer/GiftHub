// User Web App shell: boot, shared state, bottom nav and routes.
import { h, clear, icon } from '../shared/dom.js';
import { api } from '../shared/api.js';
import { tg } from '../shared/tg.js';
import { createRouter } from '../shared/router.js';
import { renderLoading, renderError } from '../shared/state.js';
import { homeScreen } from './screens/home.js';
import { appState, getProducts, gateBlocked } from './store.js';

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

// Telegram's header, background and MainButton follow the D palette (see app.css).
const LIGHT_CHROME = { background: '#f7f5ef', button: '#1d1b16', buttonText: '#ffd84d' };
const DARK_CHROME = { background: '#121212', button: '#ffd84d', buttonText: '#3d2f00' };

function setNav(active) {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);
  nav.removeAttribute('hidden');
  nav.appendChild(bottomNav(active));
}

function hideNav() {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);
  nav.setAttribute('hidden', '');
}

// Tab screens show the nav; sub-screens also get Telegram's back button.
// Every route change first drops the previous screen's MainButton.
const tab = (key, handler) => async (params) => {
  tg.hideMainButton();
  setNav(key);
  tg.backButton(null);
  return handler(params);
};
const sub = (handler, key = 'home', back = '#/') => async (params) => {
  tg.hideMainButton();
  setNav(key);
  tg.backButton(() => { location.hash = back; });
  return handler(params);
};

const orders = () => import('./screens/orders.js');

// Non-home screens are dynamic import() modules.
const routes = {
  '#/': tab('home', () => homeScreen()),
  '#/product/:id': sub(async (params) => (await import('./screens/product.js')).productScreen(params)),
  '#/topup': sub(async () => (await import('./screens/topup.js')).topupScreen()),
  '#/orders': tab('orders', async () => (await orders()).ordersScreen()),
  '#/orders/:code': sub(async (params) => (await orders()).receiptScreen(params), 'orders', '#/orders'),
  '#/referral': tab('referral', async () => (await import('./screens/referral.js')).referralScreen()),
  '#/profile': tab('profile', async () => (await import('./screens/profile.js')).profileScreen()),
};

function renderOpenInBot() {
  return h('div', { class: 'state state-full' },
    h('div', { class: 'state-icon' }, icon('telegram')),
    h('p', { class: 'state-title' }, 'Ilovani @gifthubuzbot ichida oching'),
    h('p', { class: 'state-text' }, "GiftHub faqat Telegram ichida ishlaydi."));
}

// The subscription gate is checked before the app renders; user and products load in parallel.
// A failed gate check shows a retry, never the app.
async function loadAndStart(outlet) {
  clear(outlet);
  outlet.appendChild(renderLoading());
  const failed = (err) => {
    clear(outlet);
    outlet.appendChild(renderError(err && err.message, () => loadAndStart(outlet)));
  };
  const data = Promise.all([api('/api/user/me'), getProducts({ force: true })]);
  data.catch(() => {}); // awaited below, or dropped while the gate is shown
  let blocked = false;
  try {
    const gate = await api('/api/gate/check');
    if (gateBlocked(gate)) {
      blocked = true;
      const { gateScreen } = await import('./screens/gate.js');
      const node = await gateScreen(gate.channels, () => loadAndStart(outlet));
      hideNav();
      tg.backButton(null);
      clear(outlet);
      outlet.appendChild(node);
    }
  } catch (err) {
    hideNav();
    failed(err);
    return;
  }
  if (blocked) return;
  let me;
  try {
    [me] = await data;
  } catch (err) {
    failed(err);
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
    tg.setColors(document.documentElement.getAttribute('data-theme') === 'dark' ? DARK_CHROME : LIGHT_CHROME);
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
