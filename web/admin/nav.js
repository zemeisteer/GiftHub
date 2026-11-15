// Grouped, permission-aware admin menu: sidebar on desktop, bottom sheet below 768px (CSS).
import { h, icon } from '../shared/dom.js';
import { getBadge, onBadge } from './registry.js';

// `perm` is a Permission attribute name from app/core/security.py. It only drives visibility:
// the server's require_permission stays the real check.
export const NAV = [
  { group: 'Asosiy', items: [
    { id: 'dash', label: 'Bosh sahifa', icon: 'home', perm: 'ANALYTICS_READ' },
    { id: 'orders', label: 'Buyurtmalar', icon: 'receipt', perm: 'ORDERS_READ' },
    { id: 'users', label: 'Foydalanuvchilar', icon: 'users', perm: 'USERS_READ' },
  ] },
  { group: 'Savdo', items: [
    { id: 'pricing', label: 'Narxlar', icon: 'tag', perm: 'PRICING_READ' },
    { id: 'services', label: 'Xizmatlar', icon: 'gift', perm: 'PRICING_READ' },
    { id: 'promos', label: 'Promo-kodlar', icon: 'discount', perm: 'PRICING_READ' },
    { id: 'referral', label: 'Referal', icon: 'user', perm: 'SETTINGS_READ' },
  ] },
  { group: 'Marketing', items: [
    { id: 'broadcast', label: 'Broadcast', icon: 'speakerphone', perm: 'BROADCAST_CREATE' },
    { id: 'channels', label: 'Kanallar', icon: 'telegram', perm: 'SETTINGS_READ' },
    { id: 'gate', label: 'Majburiy obuna', icon: 'shield', perm: 'SETTINGS_READ' },
  ] },
  { group: 'Tizim', items: [
    { id: 'payments', label: "To'lovlar", icon: 'card', perm: 'PAYMENTS_READ' },
    { id: 'fragment', label: 'Fragment & TON', icon: 'diamond', perm: 'SETTINGS_READ' },
    { id: 'health', label: 'Tizim holati', icon: 'heartbeat', perm: 'SETTINGS_READ' },
    { id: 'admins', label: 'Adminlar', icon: 'settings', perm: 'ADMINS_READ' },
  ] },
];

export const NAV_ITEMS = NAV.flatMap((g) => g.items);

export function findItem(id) {
  return NAV_ITEMS.find((i) => i.id === id) || null;
}

export function canSee(admin, item) {
  const perms = admin && admin.permissions;
  return Array.isArray(perms) && perms.includes(item.perm);
}

export function firstAllowed(admin) {
  return NAV_ITEMS.find((i) => canSee(admin, i)) || null;
}

function paintBadge(el, n) {
  el.textContent = n > 99 ? '99+' : String(n);
  if (n > 0) el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

// Badges update in place when a view calls setBadge().
onBadge((id, n) => {
  for (const el of document.querySelectorAll('.nav-badge')) {
    if (el.getAttribute('data-badge') === id) paintBadge(el, n);
  }
});

export function renderNav(admin, active) {
  const current = findItem(active);
  const setOpen = (open) => {
    wrap.classList.toggle('open', open);
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  };

  const menuBtn = h('button', {
    type: 'button',
    class: 'menu-btn',
    'aria-expanded': 'false',
    'aria-controls': 'admin-menu',
    onclick: () => setOpen(!wrap.classList.contains('open')),
  }, icon('menu'), h('span', { class: 'menu-btn-label' }, current ? current.label : 'Menyu'));

  const groups = NAV.map((g) => {
    const items = g.items.filter((i) => canSee(admin, i));
    if (!items.length) return null;
    return h('div', { class: 'nav-group' },
      h('p', { class: 'nav-group-title' }, g.group),
      items.map((i) => {
        const badge = h('span', { class: 'nav-badge', 'data-badge': i.id });
        paintBadge(badge, getBadge(i.id));
        return h('a', {
          href: `#/${i.id}`,
          class: i.id === active ? 'nav-item active' : 'nav-item',
          'aria-current': i.id === active ? 'page' : null,
          onclick: () => setOpen(false),
        }, icon(i.icon), h('span', { class: 'nav-label' }, i.label), badge);
      }));
  });

  const wrap = h('div', {
    class: 'admin-nav',
    onkeydown: (e) => {
      if (e.key === 'Escape' && wrap.classList.contains('open')) setOpen(false);
    },
  },
  h('div', { class: 'topbar' }, menuBtn),
  h('div', { class: 'nav-scrim', onclick: () => setOpen(false) }),
  h('nav', { id: 'admin-menu', class: 'nav-panel', 'aria-label': 'Admin menyu' }, groups));
  return wrap;
}
