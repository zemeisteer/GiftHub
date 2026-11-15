// Shared admin state: current admin, view registry, nav badges.
// View modules (Tasks 9-11) import from here and never from the versioned entry admin.js.

export const adminState = { admin: null };

export function can(perm) {
  const perms = adminState.admin && adminState.admin.permissions;
  return Array.isArray(perms) && perms.includes(perm);
}

const views = new Map();

// A view is `(params) => Promise<Node>`; params = { id, sub? }.
export function registerView(id, render) {
  views.set(id, render);
}

export function getView(id) {
  return views.get(id) || null;
}

const badges = new Map();
const listeners = new Set();

export function setBadge(id, n) {
  const count = Math.max(0, Math.floor(Number(n)) || 0);
  badges.set(id, count);
  for (const fn of listeners) fn(id, count);
}

export function getBadge(id) {
  return badges.get(id) || 0;
}

export function onBadge(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
