// Primary screen action: Telegram's MainButton when the client has one, otherwise an
// in-page button that is disabled while its handler's promise is pending.
import { h } from '../../shared/dom.js';
import { tg } from '../../shared/tg.js';

export const hasMainButton = () => Boolean(globalThis.Telegram?.WebApp?.MainButton);

export function createAction() {
  const btn = h('button', { type: 'button', class: 'btn btn-primary btn-block action-fallback', hidden: true });
  let handler = null;
  let pending = false;

  btn.addEventListener('click', async () => {
    if (pending || btn.disabled || !handler) return;
    pending = true;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    try {
      await handler();
    } catch (e) {
      if (typeof globalThis.console?.error === 'function') globalThis.console.error(e);
    } finally {
      pending = false;
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
    }
  });

  return {
    node: btn,
    // Shows the action with this label; onClick may return a promise.
    set(text, onClick) {
      handler = onClick;
      if (hasMainButton()) {
        btn.setAttribute('hidden', '');
        tg.mainButton(text, onClick);
      } else {
        btn.textContent = text;
        btn.removeAttribute('hidden');
      }
    },
    hide() {
      handler = null;
      btn.setAttribute('hidden', '');
      tg.hideMainButton();
    },
  };
}
