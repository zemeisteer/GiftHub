// In-flow confirmation dialog for dangerous actions. Resolves true (confirmed) or false (cancelled).
import { h } from '../shared/dom.js';

export function confirmDialog({ title, text, confirmLabel = 'Tasdiqlash', danger = false } = {}) {
  return new Promise((resolve) => {
    const previous = document.activeElement || null;
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      overlay.remove();
      try { previous && previous.focus && previous.focus(); } catch { /* ignore */ }
      resolve(value);
    };

    const cancelBtn = h('button', { type: 'button', class: 'btn btn-secondary', onclick: () => finish(false) }, 'Bekor qilish');
    const okBtn = h('button', {
      type: 'button',
      class: danger ? 'btn btn-danger' : 'btn btn-primary',
      onclick: () => finish(true),
    }, confirmLabel);
    const titleId = 'confirm-title';

    const overlay = h('div', {
      class: 'confirm-overlay',
      onkeydown: (e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          finish(false);
        } else if (e.key === 'Tab') {
          // Focus stays on the two buttons.
          const order = [cancelBtn, okBtn];
          const idx = order.indexOf(document.activeElement);
          const next = e.shiftKey
            ? order[idx <= 0 ? order.length - 1 : idx - 1]
            : order[idx === -1 || idx === order.length - 1 ? 0 : idx + 1];
          e.preventDefault();
          next.focus();
        }
      },
    },
    h('div', { class: 'confirm-scrim', onclick: () => finish(false) }),
    h('div', { class: 'confirm-box', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId },
      h('h2', { id: titleId, class: 'confirm-title' }, String(title || '')),
      text ? h('p', { class: 'confirm-text' }, String(text)) : null,
      h('div', { class: 'confirm-actions' }, cancelBtn, okBtn)));

    document.body.appendChild(overlay);
    cancelBtn.focus();
  });
}
