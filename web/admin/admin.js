// Admin panel shell: boot, permissions, grouped nav and view loading.
import { h, clear, icon } from '../shared/dom.js';
import { api, ApiError } from '../shared/api.js';
import { tg } from '../shared/tg.js';
import { createRouter } from '../shared/router.js';
import { renderError, renderEmpty, renderLoading } from '../shared/state.js';
import { renderNav, findItem, canSee, firstAllowed } from './nav.js';
import { adminState, getView, setBadge } from './registry.js';

export { registerView, setBadge, adminState } from './registry.js';

const NO_ACCESS = "Bu bo'lim uchun ruxsatingiz yo'q";

// id -> module path for views that live in their own file.
// A view module calls registerView(id, fn) from './registry.js' when imported.
export const VIEW_MODULES = {
  dash: './views/dash.js',
  orders: './views/orders.js',
  users: './views/users.js',
  payments: './views/payments.js',
  pricing: './views/pricing.js',
  services: './views/services.js',
  promos: './views/promos.js',
  referral: './views/referral.js',
  broadcast: './views/broadcast.js',
  channels: './views/channels.js',
  gate: './views/gate.js',
  fragment: './views/fragment.js',
  health: './views/health.js',
  admins: './views/admins.js',
};

const byId = (id) => document.getElementById(id);

function renderNoAccess(full = false) {
  return h('div', { class: full ? 'state state-full' : 'state', role: 'alert' },
    h('div', { class: 'state-icon state-icon-error' }, icon('shield')),
    h('p', { class: 'state-title' }, NO_ACCESS));
}

function renderOpenInBot() {
  return h('div', { class: 'state state-full' },
    h('div', { class: 'state-icon' }, icon('telegram')),
    h('p', { class: 'state-title' }, 'Admin panelni @gifthubuzbot ichida oching'),
    h('p', { class: 'state-text' }, 'GiftHub boshqaruvi faqat Telegram ichida ishlaydi.'));
}

function renderPlaceholder(item) {
  return h('div', { class: 'state' },
    h('div', { class: 'state-icon' }, icon(item.icon)),
    h('p', { class: 'state-title' }, item.label),
    h('p', { class: 'state-text' }, 'Tez orada'));
}

function setNav(active) {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);
  nav.removeAttribute('hidden');
  nav.appendChild(renderNav(adminState.admin, active));
}

function hideNav() {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);
  nav.setAttribute('hidden', '');
}

async function loadView(id, params) {
  const item = findItem(id);
  if (!item) return renderEmpty("Bo'lim topilmadi");
  // Permissions only drive visibility; the server still enforces. Skip loading what is hidden.
  if (!canSee(adminState.admin, item)) return renderNoAccess();
  if (VIEW_MODULES[id] && !getView(id)) await import(VIEW_MODULES[id]);
  const view = getView(id);
  return view ? view({ ...params, id }) : renderPlaceholder(item);
}

const section = (handler) => async (params) => {
  const id = params.id || (firstAllowed(adminState.admin) || {}).id;
  tg.hideMainButton();
  if (!id) return renderNoAccess(true);
  setNav(id);
  return handler(id, params);
};

const routes = {
  '#/': section((id, params) => loadView(id, params)),
  '#/:id': section((id, params) => loadView(id, params)),
  '#/:id/:sub': section((id, params) => loadView(id, params)),
};

let router = null;

export function go(hash) {
  return router.go(hash);
}

async function loadAndStart(outlet) {
  clear(outlet);
  outlet.appendChild(renderLoading({ blocks: 3 }));
  let me;
  try {
    me = await api('/api/admin/me');
  } catch (err) {
    hideNav();
    clear(outlet);
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      outlet.appendChild(renderNoAccess(true));
    } else {
      outlet.appendChild(renderError(err && err.message, () => loadAndStart(outlet)));
    }
    return;
  }
  adminState.admin = {
    id: me && me.id,
    first_name: me && me.first_name,
    role: me && me.role,
    permissions: Array.isArray(me && me.permissions) ? me.permissions : [],
  };
  router = createRouter(routes, outlet, {
    onError: (err) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return renderNoAccess();
      return renderError(err && err.message, () => router.go(location.hash || '#/'));
    },
  });
  await router.start();
  loadProblemBadge();
}

// Problem-orders count shown on "Buyurtmalar"; best effort, never blocks the shell.
function loadProblemBadge() {
  const item = findItem('orders');
  if (!canSee(adminState.admin, item)) return;
  api('/api/v1/admin/orders/problematic')
    .then((data) => setBadge('orders', data && data.counts && data.counts.total_problematic))
    .catch(() => {});
}

export async function boot() {
  const outlet = byId('outlet') || document.body;
  try {
    tg.ready();
    tg.applyTheme(document.documentElement);
    clear(outlet);
    hideNav();
  } catch (err) {
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
