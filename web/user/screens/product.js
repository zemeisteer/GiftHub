// Product page: variant -> recipient -> promo code -> pay from the wallet.
// Every amount shown comes from the server: the product price from /api/products,
// the discounted total from /api/promo/apply. The client never computes a total.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { appState, getProducts, productList, invalidateProducts, setBalance } from '../store.js';
import { renderEmpty } from './state.js';
import { createAction } from './action.js';

export const USERNAME_RX = /^@?[A-Za-z0-9_]{5,32}$/;

const CAT_ICON = { stars: 'star', premium: 'diamond', gifts: 'gift' };

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

export async function productScreen({ id } = {}) {
  const myHash = location.hash;
  const active = () => location.hash === myHash;

  const data = await getProducts();
  const items = productList(data);
  let selected = items.find((p) => p.id === id) || null;
  if (!selected) return renderEmpty('Mahsulot topilmadi', "Bu mahsulot mavjud emas yoki o'chirilgan");
  const variants = selected.cat === 'gifts' ? [] : items.filter((p) => p.cat === selected.cat);

  let mode = 'self';
  let promo = null; // { code, total } from the server
  let promoSeq = 0;
  let promoPending = null;
  let recipientsRequested = false;
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

  // --- Variants ---
  const variantButtons = variants.map((p) => h('button', {
    type: 'button',
    class: 'chip',
    dataset: { id: p.id },
    onclick: () => selectVariant(p),
  }, p.name));
  function markVariants() {
    for (const b of variantButtons) b.setAttribute('aria-pressed', b.dataset.id === selected.id ? 'true' : 'false');
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
    placeholder: '@username',
    'aria-label': 'Qabul qiluvchi username',
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
      clear(savedChips);
      const list = res && Array.isArray(res.recipients) ? res.recipients : [];
      for (const r of list) {
        const name = typeof r.recipient_username === 'string' ? r.recipient_username.replace(/^@/, '') : '';
        if (!USERNAME_RX.test(name)) continue;
        savedChips.appendChild(h('button', {
          type: 'button',
          class: 'chip',
          onclick: () => {
            recipientInput.value = `@${name}`;
            showRecipientError(null);
            tg.haptic('light');
          },
        }, `@${name}`));
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
      promoSeq++;
      promo = null;
      setPromoMsg(null);
      updateTotal();
    },
  });
  const promoMsg = h('p', { class: 'field-hint', 'aria-live': 'polite', hidden: true });
  const applyBtn = h('button', { type: 'button', class: 'btn btn-secondary', onclick: () => { applyPromo(); } }, "Qo'llash");

  function setPromoMsg(msg, kind) {
    promoMsg.textContent = msg || '';
    promoMsg.className = kind === 'error' ? 'field-error' : 'field-ok';
    if (msg) promoMsg.removeAttribute('hidden');
    else promoMsg.setAttribute('hidden', '');
  }

  function applyPromo() {
    const code = String(promoInput.value || '').trim();
    if (!code) {
      setPromoMsg('Promo-kodni kiriting', 'error');
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
        // Not a discount: nothing to attach to the order.
        promo = null;
        setPromoMsg(String(res.message || "Promo-kod qo'llandi"), 'ok');
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

  function showNotice(message, withTopup) {
    clear(notice);
    notice.appendChild(h('p', { class: 'notice-text' }, String(message || "Noma'lum xatolik")));
    if (withTopup) {
      notice.appendChild(h('button', {
        type: 'button',
        class: 'btn btn-primary',
        onclick: () => { tg.hideMainButton(); location.hash = '#/topup'; },
      }, icon('plus'), "Hamyonni to'ldirish"));
    }
    notice.removeAttribute('hidden');
  }
  function hideNotice() {
    clear(notice);
    notice.setAttribute('hidden', '');
  }

  function updateTotal() {
    const total = promo ? promo.total : selected.price;
    clear(priceEl);
    if (promo && promo.total !== selected.price) {
      priceEl.append(h('s', { class: 'price-old' }, formatSom(selected.price)), ' ');
    }
    priceEl.appendChild(h('span', { class: 'price-now' }, formatSom(total)));
    totalEl.textContent = formatSom(total);
    balanceEl.textContent = formatSom(appState.balance);
    if (active()) action.set(`To'lash · ${formatSom(total)}`, pay);
  }

  function selectVariant(p) {
    if (payInFlight || p.id === selected.id) return;
    selected = p;
    promoSeq++; // drop any promo answer computed for the previous variant
    if (promo) setPromoMsg("Promo-kodni qayta qo'llang", 'error');
    promo = null;
    tg.haptic('light');
    hideNotice();
    renderHero();
    markVariants();
    updateTotal();
  }

  async function doPay() {
    hideNotice();
    if (promoPending) await promoPending;
    let recipient;
    if (mode === 'other') {
      const v = String(recipientInput.value || '').trim();
      if (!USERNAME_RX.test(v)) {
        tg.haptic('error');
        showRecipientError("Username noto'g'ri. Masalan: @username (5–32 belgi: harf, raqam, _)");
        return;
      }
      recipient = `@${v.replace(/^@/, '')}`;
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
      if (active()) showNotice(err && err.message, isInsufficient(err));
      return;
    }
    tg.haptic('success');
    setBalance(res && res.new_balance);
    invalidateProducts();
    if (saveRecipient) {
      api('/api/v1/recipients', { method: 'POST', body: { user_id: appState.user && appState.user.id, recipient_username: recipient.replace(/^@/, '') } })
        .catch(() => { /* saving is best-effort */ });
    }
    tg.hideMainButton();
    if (active()) location.hash = '#/orders';
  }

  function pay() {
    if (!payInFlight) payInFlight = doPay().finally(() => { payInFlight = null; });
    return payInFlight;
  }

  const root = h('div', { class: 'product-page' },
    h('section', { class: 'product-hero' }, heroIcon, h('div', { class: 'product-hero-info' }, heroName, priceEl), heroBadge),
    variants.length > 1 ? h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Variant'),
      h('div', { class: 'chips chips-wrap', role: 'group', 'aria-label': 'Variantlar' }, variantButtons)) : null,
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
  return root;
}
