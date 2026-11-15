// Wallet top-up: amount (presets or custom) -> payment method -> /api/wallet/topup.
// Online providers return checkout_url, opened only through tg.openLink (https only).
import { h, clear, icon, formatSom, safeUrl } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { appState, getProducts, setBalance, refreshUser } from '../store.js';
import { renderEmpty } from './state.js';
import { createAction } from './action.js';

const PRESETS = [20000, 50000, 100000, 200000, 500000];
// app/web/routes/payments.py rejects amount < 1000; there is no upper limit server-side.
export const MIN_TOPUP = 1000;
// Methods /api/wallet/topup handles, plus the manual P2P card shown from /api/products.
const METHODS = new Set(['card', 'click', 'payme', 'autopaycard']);

let topupInFlight = null;

// "15 000" -> 15000; anything that is not a whole number -> NaN.
export function parseAmount(value) {
  const raw = String(value ?? '').replace(/[\s ]/g, '');
  return /^\d{1,12}$/.test(raw) ? Number(raw) : NaN;
}

export async function topupScreen() {
  const myHash = location.hash;
  const active = () => location.hash === myHash;

  const data = (await getProducts()) || {};
  const methods = (Array.isArray(data.payment_methods) ? data.payment_methods : [])
    .filter((m) => m && METHODS.has(m.id));
  if (!methods.length) return renderEmpty("To'lov usullari mavjud emas", "Keyinroq qayta urinib ko'ring");
  const cardSrc = data.card_info || methods.find((m) => m.id === 'card') || {};
  const card = {
    number: typeof cardSrc.card_number === 'string' ? cardSrc.card_number : '',
    holder: typeof cardSrc.card_holder === 'string' ? cardSrc.card_holder : '',
    bank: typeof cardSrc.bank_name === 'string' ? cardSrc.bank_name : '',
  };

  let amount = 50000;
  let custom = false;
  let method = (methods.find((m) => m.type === 'official') || methods.find((m) => m.id !== 'card') || methods[0]).id;
  const action = createAction();

  const amountOf = () => (custom ? parseAmount(customInput.value) : amount);

  // --- Amount ---
  const presetButtons = PRESETS.map((v) => h('button', {
    type: 'button', class: 'chip', dataset: { v: String(v) },
    onclick: () => { custom = false; amount = v; tg.haptic('light'); refresh(); },
  }, formatSom(v).replace(" so'm", '')));
  const customBtn = h('button', {
    type: 'button', class: 'chip',
    onclick: () => { custom = true; tg.haptic('light'); refresh(); customInput.focus?.(); },
  }, 'Boshqa');
  const customInput = h('input', {
    type: 'text',
    name: 'amount',
    class: 'field-input',
    inputmode: 'numeric',
    placeholder: "Summa (so'm)",
    'aria-label': "To'ldirish summasi",
    autocomplete: 'off',
    maxlength: '16',
    hidden: true,
    oninput: () => { hideNotice(); refresh(); },
  });

  // --- Method ---
  const methodButtons = methods.map((m) => h('button', {
    type: 'button', class: 'method-btn', dataset: { m: m.id },
    onclick: () => { method = m.id; tg.haptic('light'); hideNotice(); refresh(); },
  }, icon(m.id === 'card' || m.id === 'autopaycard' ? 'card' : 'check'), h('span', null, String(m.name || m.id))));

  const cardBox = h('div', { class: 'card-info', hidden: true },
    card.bank ? h('p', { class: 'card-bank' }, card.bank) : null,
    h('p', { class: 'card-number' }, card.number || '—'),
    card.holder ? h('p', { class: 'card-holder' }, card.holder) : null,
    h('p', { class: 'field-hint' }, "Ko'rsatilgan summani aynan shu kartaga o'tkazing."));

  const notice = h('div', { class: 'notice', role: 'status', hidden: true });
  function showNotice(message, kind) {
    clear(notice);
    notice.className = kind === 'error' ? 'notice notice-error' : 'notice';
    notice.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    notice.appendChild(h('p', { class: 'notice-text' }, String(message || '')));
    notice.removeAttribute('hidden');
  }
  function hideNotice() {
    clear(notice);
    notice.setAttribute('hidden', '');
  }

  function refresh() {
    for (const b of presetButtons) b.setAttribute('aria-pressed', !custom && Number(b.dataset.v) === amount ? 'true' : 'false');
    customBtn.setAttribute('aria-pressed', custom ? 'true' : 'false');
    if (custom) customInput.removeAttribute('hidden');
    else customInput.setAttribute('hidden', '');
    for (const b of methodButtons) b.setAttribute('aria-pressed', b.dataset.m === method ? 'true' : 'false');
    if (method === 'card') cardBox.removeAttribute('hidden');
    else cardBox.setAttribute('hidden', '');
    // While a request is in flight the button keeps its label and spinner; submit()'s finally re-runs this.
    if (!active() || topupInFlight) return;
    if (method === 'card') {
      action.hide();
      return;
    }
    const a = amountOf();
    action.set(Number.isSafeInteger(a) && a > 0 ? `To'ldirish · ${formatSom(a)}` : "To'ldirish", submit);
  }

  async function doSubmit() {
    hideNotice();
    const a = amountOf();
    if (!Number.isSafeInteger(a)) {
      tg.haptic('error');
      showNotice("Summani butun so'mda kiriting", 'error');
      return;
    }
    if (a < MIN_TOPUP) {
      tg.haptic('error');
      showNotice(`Minimal to'ldirish summasi: ${formatSom(MIN_TOPUP)}`, 'error');
      return;
    }
    const m = method;
    if (m === 'card') return;
    let res;
    try {
      res = await api('/api/wallet/topup', { method: 'POST', body: { amount: a, method: m } });
    } catch (err) {
      tg.haptic('error');
      if (active()) showNotice(err && err.message, 'error');
      return;
    }
    if (!active()) return;
    if (res && res.checkout_url !== undefined && res.checkout_url !== null) {
      const url = safeUrl(res.checkout_url);
      if (!url || !url.startsWith('https://')) {
        tg.haptic('error');
        showNotice("To'lov havolasi noto'g'ri. Qayta urinib ko'ring.", 'error');
        return;
      }
      tg.openLink(url);
      showNotice("To'lov sahifasi ochildi. To'lovdan so'ng balans avtomatik yangilanadi.");
      return;
    }
    if (res && typeof res.instructions === 'string' && res.instructions) {
      showNotice(res.instructions);
      return;
    }
    if (res && res.new_balance !== undefined) {
      setBalance(res.new_balance);
      balanceEl.textContent = formatSom(appState.balance);
      tg.haptic('success');
      showNotice(String(res.message || "Hamyon to'ldirildi"));
      return;
    }
    showNotice("To'lovni boshlab bo'lmadi. Qayta urinib ko'ring.", 'error');
  }

  function submit() {
    if (!topupInFlight) {
      topupInFlight = doSubmit().finally(() => {
        topupInFlight = null;
        refresh();
      });
    }
    return topupInFlight;
  }

  const balanceEl = h('span', { class: 'balance-value' }, formatSom(appState.balance));

  // Back from Click/Payme: re-read the balance. The listener removes itself once the screen is left.
  const onVisible = () => {
    if (!active()) {
      document.removeEventListener('visibilitychange', onVisible);
      return;
    }
    if (document.visibilityState !== 'visible') return;
    refreshUser().then(() => { if (active()) balanceEl.textContent = formatSom(appState.balance); });
  };
  document.addEventListener('visibilitychange', onVisible);

  const root = h('div', { class: 'topup-page' },
    h('section', { class: 'balance-card' },
      h('div', { class: 'balance-info' },
        h('span', { class: 'balance-label' }, 'Joriy balans'),
        balanceEl)),
    h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Summani tanlang'),
      h('div', { class: 'chips chips-wrap', role: 'group', 'aria-label': 'Summalar' }, presetButtons, customBtn),
      customInput),
    h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, "To'lov usuli"),
      h('div', { class: 'method-grid', role: 'group', 'aria-label': "To'lov usuli" }, methodButtons),
      cardBox),
    h('p', { class: 'field-hint' }, "Diqqat: aynan ko'rsatilgan summani to'lang, aks holda to'lov avtomatik qabul qilinmaydi."),
    notice,
    action.node);

  refresh();
  return root;
}
