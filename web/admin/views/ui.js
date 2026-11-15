// Small UI helpers shared by the admin views. Text only, through h().
import { h, icon } from '../../shared/dom.js';
import { showToast } from '../../user/screens/state.js';
import { adminState } from '../registry.js';
import { confirmDialog } from '../confirm.js';

export { showToast };

// Permission names only drive what is shown; the server enforces them.
export function can(perm) {
  const perms = adminState.admin && adminState.admin.permissions;
  return Array.isArray(perms) && perms.includes(perm);
}

export function debounce(fn, ms = 350) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

const inflight = new Set();

// One mutating action at a time per key. The key stays locked from the click (so a second tap
// cannot open a second dialog) until the request settles. `call` throws to report a failure.
export async function runAction({ button, key, confirm, call, success }) {
  if (inflight.has(key)) return false;
  inflight.add(key);
  try {
    if (confirm && !(await confirmDialog(confirm))) return false;
    if (button) button.setAttribute('disabled', '');
    const res = await call();
    const msg = typeof success === 'function' ? success(res) : success;
    if (msg) showToast(msg);
    return true;
  } catch (err) {
    showToast((err && err.message) || "Noma'lum xatolik");
    return false;
  } finally {
    inflight.delete(key);
    if (button) button.removeAttribute('disabled');
  }
}

export function pageHead(title, ...actions) {
  return h('div', { class: 'page-head' },
    h('h1', { class: 'page-title' }, title),
    actions.length ? h('div', { class: 'page-actions' }, actions) : null);
}

export function iconButton(label, ic, onclick, cls = 'btn btn-secondary') {
  return h('button', { type: 'button', class: cls, onclick }, ic ? icon(ic) : null, label);
}

// Segmented single-choice control. Returns the element; `set(value)` repaints it.
export function chips(options, value, onChange, cls = 'chips') {
  const buttons = options.map(([val, label]) => h('button', {
    type: 'button',
    class: 'chip',
    'aria-pressed': String(val === value),
    onclick: () => {
      if (val === current) return;
      set(val);
      onChange(val);
    },
  }, label));
  let current = value;
  function set(v) {
    current = v;
    options.forEach(([val], i) => {
      buttons[i].setAttribute('aria-pressed', String(val === v));
      buttons[i].classList.toggle('active', val === v);
    });
  }
  set(value);
  const root = h('div', { class: cls, role: 'group' }, buttons);
  root.set = set;
  return root;
}

export function pager({ offset, hasNext, onPrev, onNext }) {
  if (offset === 0 && !hasNext) return null;
  return h('div', { class: 'pager' },
    offset > 0 ? h('button', { type: 'button', class: 'btn btn-secondary', onclick: onPrev }, 'Oldingi') : h('span'),
    hasNext ? h('button', { type: 'button', class: 'btn btn-secondary', onclick: onNext }, 'Keyingi') : null);
}

export function inlineError(message, onRetry) {
  return h('div', { class: 'inline-error', role: 'alert' },
    h('p', null, String(message || "Noma'lum xatolik")),
    onRetry ? h('button', { type: 'button', class: 'btn btn-secondary', onclick: onRetry }, icon('refresh'), 'Qayta urinish') : null);
}

export function emptyNote(title, text) {
  return h('div', { class: 'empty-note' },
    h('p', { class: 'state-title' }, title),
    text ? h('p', { class: 'state-text' }, text) : null);
}

export function badge(text, tone = 'pending') {
  return h('span', { class: `pill pill-${tone}` }, text);
}

// Order status (stored value or legacy alias) -> [label, tone].
export function orderStatus(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'completed' || s === 'done') return ['Bajarildi', 'ok'];
  if (s === 'cancelled' || s === 'cancel' || s === 'expired') return ['Bekor qilindi', 'cancel'];
  if (s === 'failed') return ['Xatolik', 'cancel'];
  if (s === 'refunded') return ['Qaytarildi', 'cancel'];
  if (s === 'paid') return ["To'langan", 'pending'];
  if (s === 'processing') return ['Jarayonda', 'pending'];
  return ['Kutilmoqda', 'pending'];
}

const pad = (n) => String(n).padStart(2, '0');
export function formatDate(iso) {
  const d = new Date(String(iso || ''));
  if (Number.isNaN(d.getTime())) return '';
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Blob download. The blob: URL is created here from our own fetched data and never from
// user input, which is why it bypasses h()/safeUrl; it is revoked right after the click.
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.hidden = true;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
