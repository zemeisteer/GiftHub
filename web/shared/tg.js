// Thin wrapper over window.Telegram.WebApp. Every method is a safe no-op outside Telegram.
// WebApp is resolved lazily so an SDK that appears after import is still seen.
import { safeUrl } from './dom.js';

const getWebApp = () => globalThis.Telegram?.WebApp || null;

let currentMainHandler = null;
let mainGen = 0;

function clearMainHandler() {
  const wa = getWebApp();
  if (currentMainHandler && wa) {
    try { wa.MainButton.offClick(currentMainHandler); } catch { /* ignore */ }
  }
  currentMainHandler = null;
}

// Plain-assignable properties: an assigned value wins; otherwise read from WebApp at access time.
const overrides = {};
const lazy = {
  initData: () => getWebApp()?.initData || '',
  inTelegram: () => Boolean(getWebApp()?.initData),
  user: () => getWebApp()?.initDataUnsafe?.user || null,
};

export const tg = {
  ready() {
    const wa = getWebApp();
    if (!wa) return;
    try { wa.ready(); wa.expand(); } catch { /* ignore */ }
  },

  applyTheme(root) {
    const wa = getWebApp();
    const p = (wa && wa.themeParams) || {};
    const set = (name, value) => { if (value) root.style.setProperty(name, value); };
    set('--tg-bg', p.bg_color);
    set('--tg-text', p.text_color);
    set('--tg-hint', p.hint_color);
    set('--tg-secondary-bg', p.secondary_bg_color);
    let scheme = wa && wa.colorScheme;
    if (scheme !== 'dark' && scheme !== 'light') {
      const dark = typeof globalThis.matchMedia === 'function' && globalThis.matchMedia('(prefers-color-scheme: dark)').matches;
      scheme = dark ? 'dark' : 'light';
    }
    root.setAttribute('data-theme', scheme);
  },

  // Shows a main button; while onClick's promise is pending it shows progress and ignores re-clicks.
  // { disabled: true } shows it greyed out and ignores clicks.
  mainButton(text, onClick, { disabled = false } = {}) {
    const wa = getWebApp();
    if (!wa) return;
    const mb = wa.MainButton;
    const replacing = Boolean(currentMainHandler);
    clearMainHandler();
    const gen = ++mainGen;
    // A new generation never inherits a stale spinner from a replaced handler.
    if (replacing) {
      try { mb.hideProgress(); } catch { /* ignore */ }
    }
    try {
      if (disabled) mb.disable?.();
      else mb.enable?.();
    } catch { /* ignore */ }
    let busy = false;
    const handler = async () => {
      if (busy || disabled) return;
      busy = true;
      try { mb.showProgress(); } catch { /* ignore */ }
      try {
        await onClick();
      } catch (e) {
        // Callers handle their own errors; never leak an unhandled rejection from a button click.
        if (typeof globalThis.console?.error === 'function') globalThis.console.error(e);
      } finally {
        busy = false;
        if (gen === mainGen) {
          try { mb.hideProgress(); } catch { /* ignore */ }
        }
      }
    };
    currentMainHandler = handler;
    mb.setText(text);
    mb.onClick(handler);
    mb.show();
  },

  hideMainButton() {
    const wa = getWebApp();
    if (!wa) return;
    mainGen++;
    clearMainHandler();
    try { wa.MainButton.hideProgress(); wa.MainButton.hide(); } catch { /* ignore */ }
  },

  backButton(handler) {
    const wa = getWebApp();
    if (!wa) return;
    const bb = wa.BackButton;
    if (tg._backHandler) { try { bb.offClick(tg._backHandler); } catch { /* ignore */ } }
    tg._backHandler = null;
    if (typeof handler === 'function') {
      tg._backHandler = handler;
      bb.onClick(handler);
      bb.show();
    } else {
      bb.hide();
    }
  },

  haptic(kind) {
    const hf = getWebApp()?.HapticFeedback;
    if (!hf) return;
    try {
      if (kind === 'success' || kind === 'error') hf.notificationOccurred(kind);
      else hf.impactOccurred('light');
    } catch { /* ignore */ }
  },

  openLink(url) {
    const safe = safeUrl(url);
    if (!safe || !safe.startsWith('https://')) return;
    const wa = getWebApp();
    if (wa) wa.openLink(safe);
    else globalThis.open?.(safe, '_blank', 'noopener');
  },

  openTelegramLink(url) {
    const safe = safeUrl(url);
    if (!safe || !safe.startsWith('https://t.me/')) return;
    const wa = getWebApp();
    if (wa) wa.openTelegramLink(safe);
    else globalThis.open?.(safe, '_blank', 'noopener');
  },

  // Drops assigned overrides (used by tests).
  resetOverrides() {
    for (const k of Object.keys(overrides)) delete overrides[k];
  },

  _backHandler: null,
};

for (const key of Object.keys(lazy)) {
  Object.defineProperty(tg, key, {
    enumerable: true,
    get: () => (key in overrides ? overrides[key] : lazy[key]()),
    set: (v) => { overrides[key] = v; },
  });
}
