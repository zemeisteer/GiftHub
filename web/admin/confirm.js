// In-flow confirmation dialog for dangerous actions.
//   confirmDialog(opts)    -> Promise<boolean>
//   confirmWithReason(opts) -> Promise<{confirmed, value}>; opts.input = {label, required, minLength, defaultValue}
// Only one dialog can be open at a time: while one is open, another call resolves to a
// cancelled result immediately (false / {confirmed:false}) instead of stacking or queueing.
import { h } from '../shared/dom.js';

let seq = 0;

const isOpen = () => Boolean(document.querySelector('.confirm-overlay'));

function openDialog({ title, text, confirmLabel = 'Tasdiqlash', danger = false, input = null } = {}) {
  if (isOpen()) return Promise.resolve({ confirmed: false, value: '' });
  return new Promise((resolve) => {
    const previous = document.activeElement || null;
    let done = false;
    const finish = (confirmed, value = '') => {
      if (done) return;
      done = true;
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      try { previous && previous.focus && previous.focus(); } catch { /* ignore */ }
      resolve({ confirmed, value });
    };

    const cancelBtn = h('button', { type: 'button', class: 'btn btn-secondary', onclick: () => finish(false) }, 'Bekor qilish');
    const titleId = `confirm-title-${++seq}`;
    const field = input
      ? h('input', {
        type: 'text', class: 'input confirm-input', name: 'reason', value: input.defaultValue || '',
        'aria-label': input.label || 'Sabab', 'aria-describedby': `${titleId}-err`, autocomplete: 'off',
      })
      : null;
    const error = input ? h('p', { id: `${titleId}-err`, class: 'field-error confirm-error', role: 'alert', hidden: true }) : null;

    const onOk = () => {
      if (!field) { finish(true); return; }
      const value = String(field.value || '').trim();
      const min = Math.max(input.required ? 1 : 0, Number(input.minLength) || 0);
      if (value.length < min) {
        error.textContent = min > 1
          ? `${input.label || 'Sabab'} kamida ${min} ta belgidan iborat bo'lishi kerak`
          : `${input.label || 'Sabab'} kiritilishi shart`;
        error.removeAttribute('hidden');
        field.focus();
        return;
      }
      finish(true, value);
    };
    const okBtn = h('button', {
      type: 'button',
      class: danger ? 'btn btn-danger' : 'btn btn-primary',
      onclick: onOk,
    }, confirmLabel);

    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        finish(false);
      } else if (e.key === 'Tab') {
        // Focus stays on the dialog's own controls.
        const order = field ? [field, cancelBtn, okBtn] : [cancelBtn, okBtn];
        const idx = order.indexOf(document.activeElement);
        const next = e.shiftKey
          ? order[idx <= 0 ? order.length - 1 : idx - 1]
          : order[idx === -1 || idx === order.length - 1 ? 0 : idx + 1];
        e.preventDefault();
        next.focus();
      }
    };

    const overlay = h('div', { class: 'confirm-overlay' },
      h('div', { class: 'confirm-scrim', onclick: () => finish(false) }),
      h('div', { class: 'confirm-box', role: 'dialog', 'aria-modal': 'true', tabindex: '-1', 'aria-labelledby': titleId },
        h('h2', { id: titleId, class: 'confirm-title' }, String(title || '')),
        text ? h('p', { class: 'confirm-text' }, String(text)) : null,
        input ? h('label', { class: 'field confirm-field' }, h('span', { class: 'field-label' }, input.label || 'Sabab'), field, error) : null,
        h('div', { class: 'confirm-actions' }, cancelBtn, okBtn)));

    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    (field || cancelBtn).focus();
  });
}

export function confirmDialog(opts) {
  return openDialog({ ...opts, input: null }).then((r) => r.confirmed);
}

export function confirmWithReason(opts) {
  return openDialog(opts);
}
