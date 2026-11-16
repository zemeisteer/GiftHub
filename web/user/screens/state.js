// User-screen helpers: toast and clipboard. Loading/error/empty states live in shared/state.js.
import { h } from '../../shared/dom.js';

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

