// Loading / error / empty states, toast and clipboard helpers shared by the user app and the admin panel.
import { h, icon } from './dom.js';

export function skeletonCards(n = 4) {
  return Array.from({ length: n }, () => h('div', { class: 'product-card skeleton', 'aria-hidden': 'true' },
    h('div', { class: 'sk sk-icon' }),
    h('div', { class: 'sk sk-line' }),
    h('div', { class: 'sk sk-line sk-short' })));
}

// Default: a block plus a grid of card skeletons (user app). `blocks: n` renders n plain
// blocks instead (admin panel, which has no card grid).
export function renderLoading({ blocks = 0 } = {}) {
  const children = blocks > 0
    ? Array.from({ length: blocks }, () => h('div', { class: 'sk sk-block skeleton' }))
    : [h('div', { class: 'sk sk-block skeleton' }), h('div', { class: 'grid' }, skeletonCards(4))];
  return h('div', { class: 'state-loading', role: 'status', 'aria-label': 'Yuklanmoqda' }, ...children);
}

export function renderError(message, onRetry) {
  return h('div', { class: 'state', role: 'alert' },
    h('div', { class: 'state-icon state-icon-error' }, icon('alert')),
    h('p', { class: 'state-title' }, 'Xatolik yuz berdi'),
    h('p', { class: 'state-text' }, String(message || "Noma'lum xatolik")),
    typeof onRetry === 'function'
      ? h('button', { class: 'btn btn-primary', type: 'button', onclick: onRetry }, icon('refresh'), 'Qayta urinish')
      : null);
}

export function renderEmpty(title, text) {
  return h('div', { class: 'state' },
    h('div', { class: 'state-icon' }, icon('search')),
    h('p', { class: 'state-title' }, String(title)),
    text ? h('p', { class: 'state-text' }, String(text)) : null);
}

// Short status message at the bottom of the screen.
let toastTimer = null;
export function showToast(message) {
  let el = document.getElementById('toast');
  if (!el) {
    el = h('div', { id: 'toast', class: 'toast', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(el);
  }
  el.textContent = String(message);
  el.removeAttribute('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.setAttribute('hidden', ''), 2500);
}

// Clipboard copy; falls back to selecting `input` (a readonly field holding the text),
// or a temporary readonly one. On false the caller asks the user to copy by hand.
export async function copyText(value, input) {
  try {
    await globalThis.navigator.clipboard.writeText(value);
    return true;
  } catch { /* fall back below */ }
  const temp = input ? null : h('textarea', { readonly: true, class: 'copy-buffer', 'aria-hidden': 'true' });
  const el = input || temp;
  try {
    if (temp) {
      temp.value = value;
      document.body.appendChild(temp);
    }
    el.focus?.();
    el.select?.();
    return Boolean(document.execCommand?.('copy'));
  } catch {
    return false;
  } finally {
    temp?.remove();
  }
}

