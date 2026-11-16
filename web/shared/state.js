// Loading / error / empty states shared by the user app and the admin panel.
import { h, icon } from './dom.js';

export function skeletonCards(n = 4) {
  return Array.from({ length: n }, () => h('div', { class: 'product-card skeleton', 'aria-hidden': 'true' },
    h('div', { class: 'sk sk-icon' }),
    h('div', { class: 'sk sk-line' }),
    h('div', { class: 'sk sk-line sk-short' })));
}

export function renderLoading() {
  return h('div', { class: 'state-loading', role: 'status', 'aria-label': 'Yuklanmoqda' },
    h('div', { class: 'sk sk-block skeleton' }),
    h('div', { class: 'grid' }, skeletonCards(4)));
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
