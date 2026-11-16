// Order audit timeline modal: GET /api/v1/admin/orders/{code}/timeline. Every field is rendered as text.
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { formatDate } from './ui.js';

export function timelineEntry(item) {
  const transition = item.from_status
    ? `${item.from_status} → ${item.to_status}`
    : `Boshlang'ich holat: ${item.to_status}`;
  return h('li', { class: 'timeline-item' },
    h('div', { class: 'timeline-top' },
      h('b', null, transition),
      h('span', { class: 'muted small' }, formatDate(item.created_at))),
    h('div', { class: 'muted small' }, `Aktor: ${item.actor || 'SYSTEM'} | Izoh: ${item.note || "Holat o'zgardi"}`));
}

export async function openTimeline(code) {
  if (document.querySelector('.modal-overlay')) return;
  const previous = document.activeElement || null;
  const body = h('div', { class: 'modal-body', 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Yuklanmoqda...'));
  const close = () => {
    document.removeEventListener('keydown', onKey);
    overlay.remove();
    try { previous && previous.focus && previous.focus(); } catch { /* ignore */ }
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  };
  const closeBtn = h('button', { type: 'button', class: 'btn btn-secondary', onclick: close }, 'Yopish');
  const overlay = h('div', { class: 'modal-overlay' },
    h('div', { class: 'confirm-scrim', onclick: close }),
    h('div', { class: 'confirm-box modal-box', role: 'dialog', 'aria-modal': 'true', tabindex: '-1', 'aria-label': 'Buyurtma tarixi' },
      h('h2', { class: 'confirm-title' }, 'Buyurtma tarixi'),
      h('p', { class: 'confirm-text' }, `Buyurtma kodi: ${code}`),
      body,
      h('div', { class: 'confirm-actions' }, closeBtn)));
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
  closeBtn.focus();
  try {
    const data = await api(`/api/v1/admin/orders/${encodeURIComponent(code)}/timeline`);
    if (!overlay.isConnected) return;
    clear(body);
    const list = Array.isArray(data && data.timeline) ? data.timeline : [];
    body.appendChild(list.length
      ? h('ul', { class: 'timeline' }, list.map(timelineEntry))
      : h('p', { class: 'muted' }, 'Tarix topilmadi.'));
  } catch (err) {
    if (!overlay.isConnected) return;
    clear(body);
    body.appendChild(h('p', { class: 'field-error', role: 'alert' }, (err && err.message) || 'Tarixni yuklashda xatolik!'));
  }
}
