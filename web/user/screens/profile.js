// Profile: user info, balance, wallet promo code, news/support links, public offer.
import { h, clear, icon, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { appState, refreshUser, invalidateProducts } from '../store.js';

// The legacy app's profile menu links.
const NEWS_URL = 'https://t.me/gifthub_news';
const SUPPORT_URL = 'https://t.me/gifthub_support';
const OFFER_TEXT = 'Ommaviy oferta: GiftHub platformasi orqali raqamli mahsulotlar taqdim etiladi.';

function avatar(user) {
  const name = String(user.first_name || '');
  const initial = Array.from(name)[0] || '?';
  const box = h('div', { class: 'avatar', 'aria-hidden': 'true' });
  const photo = typeof user.photo_url === 'string' && user.photo_url.startsWith('https://')
    ? user.photo_url
    : tg.user && typeof tg.user.photo_url === 'string' && tg.user.photo_url.startsWith('https://') ? tg.user.photo_url : null;
  if (photo) {
    box.appendChild(h('img', {
      src: photo, alt: '', referrerpolicy: 'no-referrer',
      onerror: () => { clear(box); box.textContent = initial; },
    }));
  } else {
    box.textContent = initial;
  }
  return box;
}

// ISO timestamps become dd.mm.yyyy; display strings from the server pass through unchanged.
function joinedDate(value) {
  const s = String(value || '');
  const m = /^(\d{4})-(\d{2})-(\d{2})T/.exec(s);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : s || '—';
}

const menuItem = (ic, label, onclick) => h('button', { type: 'button', class: 'menu-item', onclick },
  icon(ic), h('span', { class: 'menu-label' }, label), icon('chevron-right'));

export async function profileScreen() {
  const user = appState.user || {};
  const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'Foydalanuvchi';
  const handle = user.username ? `@${String(user.username).replace(/^@/, '')}` : `ID: ${user.id ?? '—'}`;
  const balanceEl = h('span', { class: 'balance-value' }, formatSom(appState.balance));

  // --- Wallet promo code (bonus to balance): POST /api/promo/apply with order_total 0, like the legacy wallet.
  const promoInput = h('input', {
    type: 'text', name: 'wallet_promo', class: 'field-input', placeholder: 'Promo-kod',
    'aria-label': 'Hamyon promo-kodi', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', maxlength: '64',
  });
  const promoMsg = h('p', { class: 'field-hint', 'aria-live': 'polite', hidden: true });
  function setMsg(text, kind) {
    promoMsg.textContent = text || '';
    promoMsg.className = kind === 'error' ? 'field-error' : kind === 'ok' ? 'field-ok' : 'field-hint';
    if (text) promoMsg.removeAttribute('hidden');
    else promoMsg.setAttribute('hidden', '');
  }
  let pending = false;
  const applyBtn = h('button', {
    type: 'button', class: 'btn btn-secondary',
    onclick: async () => {
      const code = String(promoInput.value || '').trim();
      if (!code) { setMsg('Promo-kodni kiriting', 'error'); return; }
      if (pending) return;
      pending = true;
      applyBtn.disabled = true;
      try {
        const res = await api('/api/promo/apply', { method: 'POST', body: { code, order_total: 0, product_type: 'all' } });
        if (!res || res.success === false) {
          tg.haptic('error');
          setMsg((res && res.detail) || 'Promo-kod yaroqsiz', 'error');
          return;
        }
        tg.haptic('success');
        promoInput.value = '';
        setMsg(String(res.message || "Promo-kod qo'llandi"), 'ok');
        invalidateProducts();
        await refreshUser();
        balanceEl.textContent = formatSom(appState.balance);
      } catch (err) {
        tg.haptic('error');
        setMsg(err && err.message, 'error');
      } finally {
        pending = false;
        applyBtn.disabled = false;
      }
    },
  }, "Qo'llash");

  const offer = h('p', { class: 'field-hint', hidden: true }, OFFER_TEXT);
  const stat = (value, label) => h('div', { class: 'stat-card' },
    h('span', { class: 'stat-val' }, value), h('span', { class: 'stat-lbl' }, label));

  return h('div', { class: 'profile-page' },
    h('section', { class: 'profile-head' },
      h('div', { class: 'profile-id' },
        avatar(user),
        h('div', { class: 'profile-names' },
          h('h1', { class: 'profile-name' }, fullName),
          h('span', { class: 'profile-handle' }, handle))),
      h('span', { class: 'profile-balance-label' }, 'Balansingiz'),
      h('div', { class: 'profile-balance' },
        balanceEl,
        h('button', { type: 'button', class: 'btn btn-topup', onclick: () => { location.hash = '#/topup'; } }, icon('plus'), "To'ldirish"))),
    h('div', { class: 'stat-row' },
      stat(String(Number(user.orders_count) || 0), 'Buyurtmalar'),
      stat(joinedDate(user.created_at), "Ro'yxatdan o'tgan")),
    h('section', { class: 'section' },
      h('h2', { class: 'section-title' }, 'Promo-kod'),
      h('div', { class: 'field-row' }, promoInput, applyBtn),
      promoMsg),
    h('nav', { class: 'menu', 'aria-label': 'Havolalar' },
      menuItem('speakerphone', 'Yangiliklar kanali', () => tg.openTelegramLink(NEWS_URL)),
      menuItem('telegram', "Qo'llab-quvvatlash", () => tg.openTelegramLink(SUPPORT_URL)),
      menuItem('shield', 'Ommaviy oferta', () => {
        if (offer.hasAttribute('hidden')) offer.removeAttribute('hidden');
        else offer.setAttribute('hidden', '');
      })),
    offer);
}
