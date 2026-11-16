// To'lovlar: payment method switches and bank cards.
// GET /api/admin/payments, /api/admin/cards (PAYMENTS_READ); writes need SETTINGS_UPDATE (server-enforced).
// The backend has no top-up approval flow, so there is nothing to approve or reject here.
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, chips, pageHead, emptyNote, inlineError, badge, toggleSwitch as toggle, switchOn as isOn, setSwitch as setOn } from './ui.js';

const METHODS = [['click_active', 'Click'], ['payme_active', 'Payme'], ['card_active', "Karta orqali o'tkazma"]];
const CARD_TYPES = [['UZCARD', 'Uzcard'], ['HUMO', 'Humo'], ['VISA', 'Visa'], ['MASTERCARD', 'Mastercard']];

function groupDigits(value) {
  const digits = String(value || '').replace(/\D/g, '').slice(0, 16);
  return digits.replace(/(\d{4})(?=\d)/g, '$1 ');
}
function detectType(digits) {
  if (digits.startsWith('8600')) return 'UZCARD';
  if (digits.startsWith('9860')) return 'HUMO';
  if (digits.startsWith('4')) return 'VISA';
  if (digits.startsWith('5')) return 'MASTERCARD';
  return null;
}

function cardForm(card, onSaved, onCancel) {
  let type = (card && card.card_type) || 'UZCARD';
  const field = (name, label, value, attrs = {}) => h('label', { class: 'field' },
    h('span', { class: 'field-label' }, label),
    h('input', { class: 'input', name, value: value || '', autocomplete: 'off', ...attrs }));
  const number = field('card_number', 'Karta raqami', card && card.card_number, { inputmode: 'numeric', placeholder: '8600 0000 0000 0000' });
  const holder = field('card_holder', 'Karta egasi', card && card.card_holder);
  const bank = field('bank_name', 'Bank nomi', card && card.bank_name);
  const typeChips = chips(CARD_TYPES, type, (v) => { type = v; }, 'chips');
  const error = h('p', { class: 'field-error', role: 'alert', hidden: true });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');
  const form = h('form', { class: 'card-form card', novalidate: true },
    h('h3', { class: 'section-title' }, card ? 'Kartani tahrirlash' : "Yangi karta qo'shish"),
    number, holder, bank,
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Karta turi'), typeChips),
    error,
    h('div', { class: 'form-actions' },
      h('button', { type: 'button', class: 'btn btn-secondary', onclick: onCancel }, 'Bekor qilish'), submit));
  const input = (name) => form.querySelector(`[name="${name}"]`);
  input('card_number').addEventListener('input', (e) => {
    const el = e.target || input('card_number');
    el.value = groupDigits(el.value);
    const t = detectType(el.value.replace(/\D/g, ''));
    if (t) { type = t; typeChips.set(t); }
  });
  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const body = {
      card_number: input('card_number').value.trim(),
      card_holder: input('card_holder').value.trim().toUpperCase(),
      bank_name: input('bank_name').value.trim(),
      card_type: type,
      is_active: card ? !!card.is_active : true,
    };
    const problem = body.card_number.replace(/\D/g, '').length < 16
      ? "Karta raqami kamida 16 ta raqam bo'lishi kerak"
      : (!body.card_holder ? 'Karta egasining ismini kiriting' : (!body.bank_name ? 'Bank nomini kiriting' : ''));
    error.textContent = problem;
    if (problem) { error.removeAttribute('hidden'); return; }
    error.setAttribute('hidden', '');
    const ok = await runAction({
      button: submit,
      key: 'card:save',
      confirm: {
        title: card ? "Karta o'zgarishlari saqlansinmi?" : "Yangi karta qo'shilsinmi?",
        text: `${body.bank_name} ${body.card_number}: mijozlar to'lovni shu kartaga o'tkazadi.`,
        confirmLabel: "Ha, saqlash",
      },
      call: () => api(card ? `/api/admin/cards/${encodeURIComponent(card.id)}` : '/api/admin/cards', {
        method: card ? 'PUT' : 'POST', body,
      }),
      success: card ? 'Karta yangilandi' : "Yangi karta qo'shildi",
    });
    if (ok) onSaved();
  });
  return form;
}

function cardItem(c, editable, reload, edit) {
  const sw = toggle(`${c.bank_name} kartasi faol`, c.is_active, !editable, async (el) => {
    const next = !isOn(el);
    const ok = await runAction({
      button: el,
      key: `card-active:${c.id}`,
      confirm: next
        ? { title: 'Karta faol qilinsinmi?', text: `${c.bank_name} ${c.card_number} to'lovlar uchun ko'rsatiladi.`, confirmLabel: 'Faol qilish' }
        : { title: 'Karta nofaol qilinsinmi?', text: `${c.bank_name} ${c.card_number} to'lovlar uchun ko'rsatilmaydi.`, confirmLabel: 'Nofaol qilish', danger: true },
      call: () => api(`/api/admin/cards/${encodeURIComponent(c.id)}`, { method: 'PUT', body: { is_active: next } }),
      success: next ? 'Karta faol qilindi' : 'Karta nofaol qilindi',
    });
    if (ok) { setOn(el, next); reload(); }
  });
  return h('li', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, c.bank_name), badge(String(c.card_type || 'UZCARD').toUpperCase(), 'ok')),
    h('div', { class: 'bank-number mono' }, c.card_number),
    h('div', { class: 'muted' }, c.card_holder),
    h('div', { class: 'bank-actions' },
      h('span', { class: 'muted' }, c.is_active ? 'Qabul qilinmoqda' : 'Nofaol'),
      sw,
      editable ? h('button', { type: 'button', class: 'btn btn-secondary btn-sm', 'aria-label': 'Kartani tahrirlash', onclick: () => edit(c) }, 'Tahrirlash') : null,
      editable ? deleteButton(c, reload) : null));
}

function deleteButton(c, reload) {
  const b = h('button', { type: 'button', class: 'btn btn-danger btn-sm', 'aria-label': "Kartani o'chirish" }, "O'chirish");
  b.addEventListener('click', () => runAction({
    button: b,
    key: `card-delete:${c.id}`,
    confirm: {
      title: "Karta o'chirilsinmi?",
      text: `${c.bank_name} ${c.card_number} kartasi butunlay o'chiriladi.`,
      confirmLabel: "Ha, o'chirish",
      danger: true,
    },
    call: () => api(`/api/admin/cards/${encodeURIComponent(c.id)}`, { method: 'DELETE' }),
    success: "Karta o'chirildi",
  }).then((ok) => { if (ok) reload(); }));
  return b;
}

async function render() {
  const editable = can('SETTINGS_UPDATE');
  const [settingsRaw, cardsRaw] = await Promise.all([api('/api/admin/payments'), api('/api/admin/cards')]);
  const settings = settingsRaw || {};
  let saving = false;

  // The POST resets every field it omits to a default, so always send the whole current state.
  function settingsBody(patch) {
    const merged = { ...settings, ...patch };
    return {
      click_active: !!merged.click_active,
      payme_active: !!merged.payme_active,
      card_active: merged.card_active !== false,
      card_number: merged.card_number,
      card_holder: merged.card_holder,
      bank_name: merged.bank_name,
      autopaycard_active: !!merged.autopaycard_active,
      autopaycard_last4: merged.autopaycard_last4,
      autopaycard_email: merged.autopaycard_email,
    };
  }

  const methodRows = METHODS.map(([field, label]) => {
    const sw = toggle(label, field === 'card_active' ? settings[field] !== false : settings[field], !editable, async (el) => {
      if (saving) return;
      saving = true;
      const next = !isOn(el);
      const ok = await runAction({
        button: el,
        key: `method:${field}`,
        confirm: next
          ? { title: `${label} yoqilsinmi?`, text: "Mijozlar bu usul bilan to'lay oladi.", confirmLabel: 'Yoqish' }
          : { title: `${label} o'chirilsinmi?`, text: "Mijozlar bu usul bilan to'lay olmaydi.", confirmLabel: "Ha, o'chirish", danger: true },
        call: () => api('/api/admin/payments', { method: 'POST', body: settingsBody({ [field]: next }) }),
        success: "To'lov sozlamalari saqlandi",
      });
      saving = false;
      if (ok) { settings[field] = next; setOn(el, next); }
    });
    return h('li', { class: 'method-row' }, h('span', { class: 'method-name' }, label), sw);
  });

  const cardsBody = h('div', { class: 'cards-body' });
  const formSlot = h('div', { class: 'form-slot' });

  async function loadCards() {
    try {
      paintCards(await api('/api/admin/cards'));
    } catch (err) {
      clear(cardsBody);
      cardsBody.appendChild(inlineError(err && err.message, loadCards));
    }
  }
  function openForm(card) {
    clear(formSlot);
    formSlot.appendChild(cardForm(card, () => { clear(formSlot); loadCards(); }, () => clear(formSlot)));
  }
  function paintCards(list) {
    clear(cardsBody);
    const cards = Array.isArray(list) ? list : [];
    if (!cards.length) { cardsBody.appendChild(emptyNote("Kartalar yo'q")); return; }
    cardsBody.appendChild(h('ul', { class: 'bank-list' }, cards.map((c) => cardItem(c, editable, loadCards, openForm))));
  }
  paintCards(cardsRaw);

  const root = h('div', { class: 'view payments' },
    pageHead("To'lovlar"),
    h('section', { class: 'card' },
      h('h2', { class: 'section-title' }, "To'lov usullari"),
      h('ul', { class: 'method-list' }, methodRows),
      editable ? null : h('p', { class: 'muted small' }, "O'zgartirish uchun ruxsat yo'q")),
    h('section', { class: 'cards-section' },
      h('div', { class: 'section-head' },
        h('h2', { class: 'section-title' }, 'Bank kartalari'),
        editable ? h('button', { type: 'button', class: 'btn btn-primary', onclick: () => openForm(null) }, "Karta qo'shish") : null),
      formSlot,
      cardsBody));
  return root;
}

registerView('payments', render);
