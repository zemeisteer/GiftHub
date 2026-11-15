// Product page: variant (or custom Stars quantity) -> recipient -> promo code -> pay from the wallet.
// Every amount shown comes from the server: package prices from /api/products, custom Stars
// prices from /api/products?stars_amount=N, the discounted total from /api/promo/apply.
// The client never computes a total.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { appState, getProducts, productList, invalidateProducts, setBalance, refreshUser, takePrefill } from '../store.js';
import { renderEmpty } from './state.js';
import { createAction } from './action.js';

// Telegram usernames start with a letter; 5–32 chars. Telegram user IDs are sent as plain digits.
export const USERNAME_RX = /^@?[A-Za-z][A-Za-z0-9_]{4,31}$/;
export const TG_ID_RX = /^\d{5,15}$/;
// Legacy calculator bounds (legacy app calcStarsInput: min 15, max 50000).
export const STARS_MIN = 15;
export const STARS_MAX = 50000;
const CUSTOM_DEBOUNCE_MS = 300;

const CAT_ICON = { stars: 'star', premium: 'diamond', gifts: 'gift' };

// "@name" for a username, the digits for a Telegram ID, otherwise null.
export function parseRecipient(value) {
  const s = String(value ?? '').trim();
  if (TG_ID_RX.test(s)) return s;
  if (USERNAME_RX.test(s)) return `@${s.replace(/^@/, '')}`;
  return null;
}

// One order at a time for the whole module, so a second rendered screen or a fallback
// button can never submit while another order is in flight.
let payInFlight = null;

// InsufficientBalanceError -> HTTP 400 "Balansingizda mablag' yetarli emas! ..." (app/core/exceptions.py).
const isInsufficient = (err) => Boolean(err) && (err.status === 402
  || (err.status === 400 && /yetarli emas|insufficient/i.test(String(err.message || ''))));

function selfRecipient() {
  const u = appState.user || {};
  if (u.username) return `@${String(u.username).replace(/^@/, '')}`;
  return u.id !== undefined && u.id !== null ? String(u.id) : null;
}

const customStars = (amount, price = null, discount = 0) => ({
  id: 'stars-custom', cat: 'stars', type: 'stars', amount, itemTitle: `${amount} Stars`, name: `${amount} Stars`, price, discount,
});

export async function productScreen({ id } = {}) {
  const myHash = location.hash;
  const active = () => location.hash === myHash;

  const data = await getProducts();
  const items = productList(data);
  // 'stars-custom' (from "Yana sotib olish") opens the Stars page on the custom quantity.
  const wantCustom = id === 'stars-custom';
  let selected = (wantCustom ? items.find((p) => p.cat === 'stars') : items.find((p) => p.id === id)) || null;
  const pre = takePrefill(id);
  if (!selected) return renderEmpty('Mahsulot topilmadi', "Bu mahsulot mavjud emas yoki o'chirilgan");
  const variants = selected.cat === 'gifts' ? [] : items.filter((p) => p.cat === selected.cat);
  const allowCustom = selected.cat === 'stars';

  let mode = 'self';
  let promo = null; // { code, total } from the server
  let promoSeq = 0;
  let promoPending = null;
  let recipientsRequested = false;
  let customMode = false;
  let customSeq = 0;
  let customTimer = null;
  // Set when an order's outcome is unknown (network drop/timeout): no second pay from this screen.
  let locked = false;
  const action = createAction();

  // --- Hero ---
  const heroIcon = h('span', { class: `product-icon product-icon-lg ic-${selected.cat}` });
  const heroName = h('h1', { class: 'product-title' });
  const heroBadge = h('span', { class: 'badge badge-inline', hidden: true });
  const priceEl = h('div', { class: 'product-hero-price', 'aria-live': 'polite' });

  function renderHero() {
    clear(heroIcon);
    heroIcon.className = `product-icon product-icon-lg ic-${selected.cat}`;
    heroIcon.appendChild(selected.emoji ? h('span', { class: 'emoji' }, selected.emoji) : icon(CAT_ICON[selected.cat]));
    heroName.textContent = selected.name;
    if (selected.discount > 0) {
      heroBadge.textContent = `-${selected.discount}%`;
      heroBadge.removeAttribute('hidden');
    } else {
      heroBadge.setAttribute('hidden', '');
    }
  }

  // --- Variants and custom Stars quantity ---
  const variantButtons = variants.map((p) => h('button', {
    type: 'button',
    class: 'chip',
    dataset: { id: p.id },
    onclick: () => selectVariant(p),
  }, p.name));
  const customBtn = allowCustom ? h('button', {
    type: 'button', class: 'chip', dataset: { id: 'stars-custom' }, onclick: () => selectCustom(),
  }, 'Boshqa miqdor') : null;
  if (customBtn) variantButtons.push(customBtn);
  const customInput = h('input', {
    type: 'text',
    name: 'stars_amount',
    class: 'field-input',
    inputmode: 'numeric',
    placeholder: `Stars soni (${STARS_MIN}–${formatSom(STARS_MAX).replace(" so'm", '')})`,
    'aria-label': 'Stars soni',
    autocomplete: 'off',
    maxlength: '6',
    oninput: () => onCustomInput(),
  });
  const customHint = h('p', { class: 'field-hint', 'aria-live': 'polite' });
  const customBox = h('div', { class: 'custom-amount', hidden: true }, customInput, customHint);

  function markVariants() {
    const cur = customMode ? 'stars-custom' : selected.id;
    for (const b of variantButtons) b.setAttribute('aria-pressed', b.dataset.id === cur ? 'true' : 'false');
  }

  function dropPromo(msg) {
    promoSeq++; // drop any promo answer computed for the previous product/amount
    if (promo && msg) setPromoMsg(msg, 'error');
    promo = null;
  }

  function selectVariant(p) {
    if (payInFlight || locked || (!customMode && p.id === selected.id)) return;
    customMode = false;
    customSeq++;
    clearTimeout(customTimer);
    customBox.setAttribute('hidden', '');
    selected = p;
    dropPromo("Promo-kodni qayta qo'llang");
    tg.haptic('light');
    hideNotice();
    renderHero();
    markVariants();
    updateTotal();
  }

  function selectCustom() {
    if (payInFlight || locked || customMode) return;
    customMode = true;
    tg.haptic('light');
    hideNotice();
    customBox.removeAttribute('hidden');
    customInput.focus?.();
    onCustomInput();
    markVariants();
  }

  function setCustomHint(msg, kind) {
    customHint.textContent = msg || '';
    customHint.className = kind === 'error' ? 'field-error' : 'field-hint';
  }

  function onCustomInput() {
    const raw = String(customInput.value || '').replace(/[\s ]/g, '');
    const n = /^\d{1,6}$/.test(raw) ? Number(raw) : NaN;
    customSeq++;
    clearTimeout(customTimer);
    dropPromo("Promo-kodni qayta qo'llang");
    if (!Number.isInteger(n) || n < STARS_MIN || n > STARS_MAX) {
      selected = customStars(Number.isInteger(n) ? n : 0);
      if (!Number.isInteger(n)) selected.name = 'Stars';
      setCustomHint(raw ? `Miqdor ${STARS_MIN} dan ${formatSom(STARS_MAX).replace(" so'm", '')} gacha bo'lishi kerak` : `Kamida ${STARS_MIN} Stars`, raw ? 'error' : 'hint');
      renderHero();
      updateTotal();
      return;
    }
    selected = customStars(n);
    setCustomHint('Narx hisoblanmoqda…', 'hint');
    renderHero();
    updateTotal();
    const seq = customSeq;
    customTimer = setTimeout(() => priceCustom(seq, n), CUSTOM_DEBOUNCE_MS);
  }

  async function priceCustom(seq, n) {
    let res = null;
    let err = null;
    try {
      res = await api(`/api/products?stars_amount=${n}`);
    } catch (e) {
      err = e;
    }
    if (seq !== customSeq || !active() || !customMode) return; // a newer amount or another screen
    const calc = res && res.custom_stars_calc;
    const raw = calc ? calc.total_price_uzs : null;
    const price = raw === null || raw === undefined || raw === '' ? NaN : Number(raw);
    if (err || !Number.isFinite(price) || price <= 0 || (calc.amount !== undefined && Number(calc.amount) !== n)) {
      setCustomHint(err ? err.message : "Narxni olib bo'lmadi", 'error');
      return;
    }
    selected = customStars(n, price, Number(calc.discount_percent) || 0);
    setCustomHint(null);
    renderHero();
    updateTotal();
  }

  // --- Recipient ---
  const selfBtn = h('button', { type: 'button', class: 'seg-btn', onclick: () => setMode('self') }, "O'zimga");
  const otherBtn = h('button', { type: 'button', class: 'seg-btn', onclick: () => setMode('other') }, 'Boshqa odamga');
  const selfBox = h('p', { class: 'field-hint' }, `Siz (${selfRecipient() || '—'})`);
  const recipientError = h('p', { class: 'field-error', role: 'alert', hidden: true });
  const recipientInput = h('input', {
    type: 'text',
    name: 'recipient',
    class: 'field-input',
    placeholder: '@username yoki ID',
    'aria-label': 'Qabul qiluvchi username yoki ID',
    autocomplete: 'off',
    autocapitalize: 'off',
    spellcheck: 'false',
    maxlength: '33',
    oninput: () => showRecipientError(null),
  });
  const savedChips = h('div', { class: 'chips chips-wrap', role: 'group', 'aria-label': 'Saqlangan qabul qiluvchilar' });
  const saveBox = h('input', { type: 'checkbox', name: 'save_recipient' });
  const otherBox = h('div', { class: 'recipient-other', hidden: true },
    recipientInput,
    recipientError,
    savedChips,
    h('label', { class: 'check' }, saveBox, h('span', null, 'Qabul qiluvchini saqlash')));

  function showRecipientError(msg) {
    recipientError.textContent = msg || '';
    if (msg) recipientError.removeAttribute('hidden');
    else recipientError.setAttribute('hidden', '');
  }

  function setMode(m) {
    mode = m;
    selfBtn.setAttribute('aria-pressed', m === 'self' ? 'true' : 'false');
    otherBtn.setAttribute('aria-pressed', m === 'other' ? 'true' : 'false');
    if (m === 'self') {
      selfBox.removeAttribute('hidden');
      otherBox.setAttribute('hidden', '');
      showRecipientError(null);
    } else {
      selfBox.setAttribute('hidden', '');
      otherBox.removeAttribute('hidden');
      loadSavedRecipients();
    }
  }

  function loadSavedRecipients() {
    const uid = appState.user && appState.user.id;
    if (recipientsRequested || !Number.isSafeInteger(Number(uid))) return;
    recipientsRequested = true;
    api(`/api/v1/recipients?user_id=${encodeURIComponent(String(uid))}`).then((res) => {
      if (!active()) return;
      clear(savedChips);
      const list = res && Array.isArray(res.recipients) ? res.recipients : [];
      for (const r of list) {
        const value = parseRecipient(typeof r.recipient_username === 'string' ? r.recipient_username : '');
        if (!value) continue;
        savedChips.appendChild(h('button', {
          type: 'button',
          class: 'chip',
          onclick: () => {
            recipientInput.value = value;
            showRecipientError(null);
            tg.haptic('light');
          },
        }, value));
      }
    }).catch(() => { /* saved recipients are optional */ });
  }

  // --- Promo ---
  const promoInput = h('input', {
    type: 'text',
    name: 'promo',
    class: 'field-input',
    placeholder: 'Promo-kod',
    'aria-label': 'Promo-kod',
    autocomplete: 'off',
    autocapitalize: 'characters',
    spellcheck: 'false',
    maxlength: '64',
    // Editing the code drops an applied discount, so the paid code is always the one shown.
    oninput: () => {
      if (!promo && !promoPending) return;
      dropPromo(null);
      setPromoMsg(null);
      updateTotal();
    },
  });
  const promoMsg = h('p', { class: 'field-hint', 'aria-live': 'polite', hidden: true });
  const applyBtn = h('button', { type: 'button', class: 'btn btn-secondary', onclick: () => { applyPromo(); } }, "Qo'llash");

  function setPromoMsg(msg, kind) {
    promoMsg.textContent = msg || '';
    promoMsg.className = kind === 'error' ? 'field-error' : kind === 'ok' ? 'field-ok' : 'field-hint';
    if (msg) promoMsg.removeAttribute('hidden');
    else promoMsg.setAttribute('hidden', '');
  }

  function applyPromo() {
    const code = String(promoInput.value || '').trim();
    if (!code) {
      setPromoMsg('Promo-kodni kiriting', 'error');
      return Promise.resolve();
    }
    if (selected.price === null) {
      setPromoMsg('Avval miqdorni tanlang', 'error');
      return Promise.resolve();
    }
    if (promoPending) return promoPending;
    const seq = ++promoSeq;
    const product = selected;
    applyBtn.disabled = true;
    promoPending = (async () => {
      let res = null;
      let err = null;
      try {
        res = await api('/api/promo/apply', { method: 'POST', body: { code, order_total: product.price, product_type: product.type } });
      } catch (e) {
        err = e;
      }
      if (seq !== promoSeq || !active()) return;
      if (err || !res || res.success === false) {
        promo = null;
        tg.haptic('error');
        setPromoMsg(err ? err.message : (res && res.detail) || 'Promo-kod yaroqsiz', 'error');
        updateTotal();
        return;
      }
      if (res.reward_type === 'balance_bonus') {
        // A wallet bonus code, not a discount: never attached to the order.
        promo = null;
        setPromoMsg("Bu kod hamyon uchun — Profil'da qo'llang", 'hint');
        updateTotal();
        return;
      }
      const raw = res.new_total ?? res.final_price;
      const total = raw === null || raw === undefined || raw === '' ? NaN : Number(raw);
      if (!Number.isFinite(total) || total < 0) {
        promo = null;
        setPromoMsg("Promo-kodni qo'llab bo'lmadi", 'error');
        updateTotal();
        return;
      }
      promo = { code: String(res.code || code), total };
      tg.haptic('success');
      setPromoMsg(String(res.message || "Promo-kod qo'llandi"), 'ok');
      updateTotal();
    })().finally(() => {
      promoPending = null;
      applyBtn.disabled = false;
    });
    return promoPending;
  }

  // --- Summary, notices, pay ---
  const balanceEl = h('span', { class: 'summary-value' });
  const totalEl = h('span', { class: 'summary-value summary-total' });
  const notice = h('div', { class: 'notice notice-error', role: 'alert', hidden: true });

  function showNotice(message, button) {
    clear(notice);
    notice.appendChild(h('p', { class: 'notice-text' }, String(message || "Noma'lum xatolik")));
    if (button) {
      notice.appendChild(h('button', {
        type: 'button',
        class: 'btn btn-primary',
        onclick: () => { tg.hideMainButton(); location.hash = button.hash; },
      }, button.icon ? icon(button.icon) : null, button.label));
    }
    notice.removeAttribute('hidden');
  }
  function hideNotice() {
    clear(notice);
    notice.setAttribute('hidden', '');
  }

  function renderBalance() {
    balanceEl.textContent = formatSom(appState.balance);
  }

  function updateTotal() {
    const total = promo ? promo.total : selected.price;
    clear(priceEl);
    if (total === null) {
      priceEl.appendChild(h('span', { class: 'price-now' }, '—'));
    } else {
      if (promo && promo.total !== selected.price) {
        priceEl.append(h('s', { class: 'price-old' }, formatSom(selected.price)), ' ');
      }
      priceEl.appendChild(h('span', { class: 'price-now' }, formatSom(total)));
    }
    totalEl.textContent = total === null ? '—' : formatSom(total);
    renderBalance();
    // While an order is in flight the button keeps its label and spinner; pay()'s finally re-runs this.
    if (!active() || payInFlight) return;
    if (locked || total === null) action.set("To'lash", pay, { disabled: true });
    else action.set(`To'lash · ${formatSom(total)}`, pay);
  }

  async function doPay() {
    if (locked) return;
    hideNotice();
    if (promoPending) await promoPending;
    if (selected.price === null) return;
    let recipient;
    if (mode === 'other') {
      recipient = parseRecipient(recipientInput.value);
      if (!recipient) {
        tg.haptic('error');
        showRecipientError("Username noto'g'ri. @username (harf bilan boshlanadi, 5–32 belgi) yoki ID raqamini kiriting");
        return;
      }
    } else {
      recipient = selfRecipient();
    }
    const product = selected;
    const body = { product_type: product.type, item_title: product.itemTitle, amount: product.amount, recipient_username: recipient };
    if (promo) body.promo_code = promo.code;
    const saveRecipient = mode === 'other' && saveBox.checked;

    let res;
    try {
      res = await api('/api/orders/create', { method: 'POST', body });
    } catch (err) {
      tg.haptic('error');
      if (err && err.status === 0) {
        // Timeout or dropped connection: the order may exist. Never invite a blind retry.
        locked = true;
        invalidateProducts();
        refreshUser().then(() => { if (active()) renderBalance(); });
        if (active()) {
          showNotice("Buyurtma holati noma'lum. Buyurtmalarni tekshiring.", { hash: '#/orders', label: "Buyurtmalarni ko'rish", icon: 'receipt' });
        }
        return;
      }
      if (isInsufficient(err)) {
        refreshUser().then(() => { if (active()) renderBalance(); });
        if (active()) showNotice(err.message, { hash: '#/topup', label: "Hamyonni to'ldirish", icon: 'plus' });
        return;
      }
      if (active()) showNotice(err && err.message);
      return;
    }
    tg.haptic('success');
    setBalance(res && res.new_balance);
    invalidateProducts();
    if (saveRecipient) {
      api('/api/v1/recipients', { method: 'POST', body: { user_id: appState.user && appState.user.id, recipient_username: recipient.replace(/^@/, '') } })
        .catch(() => { /* saving is best-effort */ });
    }
    if (active()) {
      tg.hideMainButton();
      location.hash = '#/orders';
    }
  }

  function pay() {
    if (!payInFlight) {
      payInFlight = doPay().finally(() => {
        payInFlight = null;
        updateTotal();
      });
    }
    return payInFlight;
  }

  const root = h('div', { class: 'product-page' },
    h('section', { class: 'product-hero' }, heroIcon, h('div', { class: 'product-hero-info' }, heroName, priceEl), heroBadge),
    variantButtons.length > 1 ? h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Variant'),
      h('div', { class: 'chips chips-wrap', role: 'group', 'aria-label': 'Variantlar' }, variantButtons),
      customBox) : null,
    h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Qabul qiluvchi'),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'Qabul qiluvchi' }, selfBtn, otherBtn),
      selfBox,
      otherBox),
    h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Promo-kod'),
      h('div', { class: 'field-row' }, promoInput, applyBtn),
      promoMsg),
    h('section', { class: 'summary' },
      h('div', { class: 'summary-row' }, h('span', null, 'Balansingiz'), balanceEl),
      h('div', { class: 'summary-row' }, h('span', null, 'Jami'), totalEl)),
    notice,
    action.node);

  renderHero();
  markVariants();
  setMode('self');
  updateTotal();
  // Buy again: the old order's recipient and Stars quantity; the price is fetched as usual.
  const preRecipient = pre && parseRecipient(pre.recipient);
  if (preRecipient && preRecipient !== selfRecipient()) {
    setMode('other');
    recipientInput.value = preRecipient;
  }
  if (wantCustom) {
    if (pre && Number.isInteger(pre.starsAmount)) customInput.value = String(pre.starsAmount);
    selectCustom();
  }
  return root;
}
