// Thin wrapper over window.Telegram.WebApp. Every method is a safe no-op outside Telegram.

const WebApp = globalThis.Telegram?.WebApp || null;
let currentMainHandler = null;

function clearMainHandler() {
  if (currentMainHandler && WebApp) {
    try { WebApp.MainButton.offClick(currentMainHandler); } catch { /* ignore */ }
  }
  currentMainHandler = null;
}

export const tg = {
  initData: (WebApp && WebApp.initData) || '',
  inTelegram: Boolean(WebApp && WebApp.initData),
  user: (WebApp && WebApp.initDataUnsafe && WebApp.initDataUnsafe.user) || null,

  ready() {
    if (!WebApp) return;
    try { WebApp.ready(); WebApp.expand(); } catch { /* ignore */ }
  },

  applyTheme(root) {
    const p = (WebApp && WebApp.themeParams) || {};
    const set = (name, value) => { if (value) root.style.setProperty(name, value); };
    set('--tg-bg', p.bg_color);
    set('--tg-text', p.text_color);
    set('--tg-hint', p.hint_color);
    set('--tg-secondary-bg', p.secondary_bg_color);
    let scheme = WebApp && WebApp.colorScheme;
    if (scheme !== 'dark' && scheme !== 'light') {
      const dark = typeof globalThis.matchMedia === 'function' && globalThis.matchMedia('(prefers-color-scheme: dark)').matches;
      scheme = dark ? 'dark' : 'light';
    }
    root.setAttribute('data-theme', scheme);
  },

  // Shows a main button; while onClick's promise is pending it shows progress and ignores re-clicks.
  mainButton(text, onClick) {
    if (!WebApp) return;
    const mb = WebApp.MainButton;
    clearMainHandler();
    let busy = false;
    const handler = async () => {
      if (busy) return;
      busy = true;
      try { mb.showProgress(); } catch { /* ignore */ }
      try {
        await onClick();
      } finally {
        busy = false;
        try { mb.hideProgress(); } catch { /* ignore */ }
      }
    };
    currentMainHandler = handler;
    mb.setText(text);
    mb.onClick(handler);
    mb.show();
  },

  hideMainButton() {
    if (!WebApp) return;
    clearMainHandler();
    try { WebApp.MainButton.hideProgress(); WebApp.MainButton.hide(); } catch { /* ignore */ }
  },

  backButton(handler) {
    if (!WebApp) return;
    const bb = WebApp.BackButton;
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
    const hf = WebApp && WebApp.HapticFeedback;
    if (!hf) return;
    try {
      if (kind === 'success' || kind === 'error') hf.notificationOccurred(kind);
      else hf.impactOccurred('light');
    } catch { /* ignore */ }
  },

  openLink(url) {
    if (WebApp) WebApp.openLink(url);
    else globalThis.open?.(url, '_blank', 'noopener');
  },

  openTelegramLink(url) {
    if (WebApp) WebApp.openTelegramLink(url);
    else globalThis.open?.(url, '_blank', 'noopener');
  },

  _backHandler: null,
};
