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
