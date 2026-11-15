// Shared user-app state. Screens import this, never app.js: app.js is the entry and is
// loaded as app.js?v=..., so importing it again would create a second module instance.
import { api } from '../shared/api.js';

export const appState = { user: null, balance: 0, products: null };

const PRODUCTS_TTL_MS = 60_000;
let productsAt = 0;
let productsPending = null;

// Fresh cached /api/products response, or null.
export function cachedProducts() {
  return appState.products && Date.now() - productsAt < PRODUCTS_TTL_MS ? appState.products : null;
}

// Balance or prices changed (e.g. after a purchase): the next getProducts() refetches.
export function invalidateProducts() {
  productsAt = 0;
}

// The server's new balance (e.g. /api/orders/create new_balance) replaces the cached one.
export function setBalance(value) {
  if (value === null || value === undefined || value === '') return;
  const n = Number(value);
  if (!Number.isFinite(n)) return;
  appState.balance = n;
  if (appState.user) appState.user.balance = n;
}

const price = (v) => (v !== null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null);

// Flattens the /api/products response into one list. Every price is a server field.
// `id` is the client slug (stars-<amount>, premium-<months>, gift-<id>); `type`, `amount`
// and `itemTitle` are what /api/orders/create needs to price the order on the server.
export function productList(data) {
  const out = [];
  const d = data || {};
  for (const p of Array.isArray(d.stars_packages) ? d.stars_packages : []) {
    const amount = Number(p.amount);
    if (price(p.price_uzs) === null || !Number.isInteger(amount) || amount <= 0) continue;
    out.push({ id: `stars-${amount}`, cat: 'stars', type: 'stars', amount, itemTitle: `${amount} Stars`, name: `${amount} Stars`, price: price(p.price_uzs), discount: Number(p.discount_pct) || 0 });
  }
  for (const p of Array.isArray(d.premium_packages) ? d.premium_packages : []) {
    const months = Number(p.months);
    if (price(p.price_uzs) === null || !Number.isInteger(months) || months <= 0) continue;
    const name = String(p.name || `Premium — ${months} oy`);
    out.push({ id: `premium-${months}`, cat: 'premium', type: 'premium', amount: months, itemTitle: name, name, price: price(p.price_uzs), discount: 0 });
  }
  for (const g of Array.isArray(d.gifts) ? d.gifts : []) {
    if (price(g.price_uzs) === null || g.id === undefined || g.id === null || g.id === '') continue;
    const emoji = typeof g.icon === 'string' && g.icon.length <= 8 ? g.icon : null;
    // The server finds the gift price by item_title == gift id (pricing_service.calculate_gift_price).
    out.push({ id: `gift-${String(g.id)}`, cat: 'gifts', type: 'gift', amount: 1, itemTitle: String(g.id), name: String(g.name || "Sovg'a"), price: price(g.price_uzs), discount: 0, emoji });
  }
  return out;
}

// Product name for an order's item_title: gift orders store the gift id (R6).
export function orderTitle(productType, itemTitle) {
  const raw = String(itemTitle ?? '');
  if (productType === 'gift') {
    const g = productList(cachedProducts() || appState.products).find((p) => p.cat === 'gifts' && p.itemTitle === raw);
    if (g) return g.name;
  }
  return raw;
}

// /api/gate/check result: blocked only when the server says so and lists channels (legacy rule).
export const gateBlocked = (res) => Boolean(res) && res.all_passed === false
  && Array.isArray(res.channels) && res.channels.length > 0;

// One-shot form prefill handed from "Yana sotib olish" to the product screen.
let prefill = null;
export function setPrefill(slug, data) {
  prefill = { slug, at: Date.now(), ...data };
}
export function takePrefill(slug) {
  const p = prefill;
  prefill = null;
  return p && p.slug === slug && Date.now() - p.at < 60_000 ? p : null;
}

// Re-reads /api/user/me (balance may have changed server-side). Failures keep the cached values.
export async function refreshUser() {
  try {
    const me = await api('/api/user/me');
    if (me && typeof me === 'object') {
      appState.user = me;
      setBalance(me.balance);
    }
  } catch { /* keep current state */ }
  return appState.user;
}

export function getProducts({ force = false } = {}) {
  if (!force) {
    const fresh = cachedProducts();
    if (fresh) return Promise.resolve(fresh);
    if (productsPending) return productsPending;
  }
  const p = api('/api/products').then((data) => {
    appState.products = data || {};
    productsAt = Date.now();
    return appState.products;
  }).finally(() => { if (productsPending === p) productsPending = null; });
  productsPending = p;
  return p;
}
