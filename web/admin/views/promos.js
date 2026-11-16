// Promo-kodlar: list, create, activate/deactivate, delete.
// GET/POST /api/admin/promocodes, POST .../{id}/toggle, DELETE .../{id} (PRICING_READ / PRICING_UPDATE).
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, emptyNote, inlineError, badge, chips } from './ui.js';
import { field, readForm, firstProblem, formError } from '../forms.js';

const TYPES = [['discount_percent', 'Chegirma (%)'], ['balance_bonus', "Balans bonusi (so'm)"]];
const typeLabel = (t) => (TYPES.find(([v]) => v === t) || [null, String(t || '')])[1];

function promoForm(onSaved, onCancel) {
  let type = 'discount_percent';
  const error = formError();
  const typeChips = chips(TYPES, type, (v) => { type = v; }, 'chips');
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');
  const form = h('form', { class: 'card card-form', novalidate: true },
    h('h3', { class: 'section-title' }, "Yangi promo-kod qo'shish"),
    h('div', { class: 'form-grid' },
      field({ label: 'Promo-kod', name: 'code', attrs: { autocapitalize: 'characters' } }),
      field({ label: 'Qiymati (% yoki so\'m)', name: 'reward_value', type: 'number', value: 10, min: 0, step: 'any' }),
      field({ label: 'Foydalanish limiti', name: 'max_uses', type: 'number', value: 100, min: 1, step: 1 }),
      field({ label: "Minimal buyurtma (so'm)", name: 'min_order_amount', type: 'number', value: 0, min: 0, step: 'any' })),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Turi'), typeChips),
    error,
    h('div', { class: 'form-actions' },
      h('button', { type: 'button', class: 'btn btn-secondary', onclick: onCancel }, 'Bekor qilish'), submit));

  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const f = readForm(form);
    const body = {
      code: f.code,
      reward_type: type,
      reward_value: f.reward_value,
      max_uses: f.max_uses,
      min_order_amount: f.min_order_amount === null ? 0 : f.min_order_amount,
      is_active: true,
    };
    const valueRule = type === 'discount_percent'
      ? { label: 'Chegirma foizi', gt: 0, max: 100 }
      : { label: 'Bonus summasi', gt: 0 };
    const problem = !body.code
      ? 'Promo-kod nomini kiriting'
      : firstProblem([
        [body.reward_value, valueRule],
        [body.max_uses, { label: 'Foydalanish limiti', min: 1, int: true }],
        [body.min_order_amount, { label: 'Minimal buyurtma', min: 0 }],
      ]);
    if (problem) { error.show(problem); return; }
    error.hide();
    const ok = await runAction({
      button: submit,
      key: 'promo:new',
      confirm: {
        title: "Promo-kod qo'shilsinmi?",
        text: `${body.code.toUpperCase()}: ${typeLabel(type)} ${body.reward_value}, ${body.max_uses} marta.`,
        confirmLabel: "Ha, qo'shish",
      },
      call: () => api('/api/admin/promocodes', { method: 'POST', body }),
      success: 'Promo-kod yaratildi',
    });
    if (ok) onSaved();
  });
  return form;
}

function promoCard(p, editable, reload) {
  const toggle = h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, p.is_active ? "To'xtatish" : 'Faollashtirish');
  toggle.addEventListener('click', () => runAction({
    button: toggle,
    key: `promo:${p.id}`,
    confirm: p.is_active
      ? { title: "Promo-kod to'xtatilsinmi?", text: `${p.code} endi ishlamaydi.`, confirmLabel: "Ha, to'xtatish", danger: true }
      : { title: 'Promo-kod faollashtirilsinmi?', text: `${p.code} yana ishlaydi.`, confirmLabel: 'Faollashtirish' },
    call: () => api(`/api/admin/promocodes/${encodeURIComponent(p.id)}/toggle`, { method: 'POST' }),
    success: 'Holat yangilandi',
  }).then((ok) => { if (ok) reload(); }));
  const del = h('button', { type: 'button', class: 'btn btn-danger btn-sm', 'aria-label': "Promo-kodni o'chirish" }, "O'chirish");
  del.addEventListener('click', () => runAction({
    button: del,
    key: `promo:${p.id}`,
    confirm: { title: "Promo-kod o'chirilsinmi?", text: `${p.code} butunlay o'chiriladi.`, confirmLabel: "Ha, o'chirish", danger: true },
    call: () => api(`/api/admin/promocodes/${encodeURIComponent(p.id)}`, { method: 'DELETE' }),
    success: "Promo-kod o'chirildi",
  }).then((ok) => { if (ok) reload(); }));
  return h('li', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', { class: 'mono' }, p.code), badge(p.is_active ? 'Faol' : 'Nofaol', p.is_active ? 'ok' : 'cancel')),
    h('div', { class: 'kv' }, h('span', null, 'Turi'), h('span', null, typeLabel(p.reward_type))),
    h('div', { class: 'kv' }, h('span', null, 'Qiymati'), h('b', null, String(p.reward_value))),
    h('div', { class: 'kv' }, h('span', null, 'Ishlatilgan'), h('span', null, `${p.current_uses} / ${p.max_uses}`)),
    Number(p.min_order_amount) > 0 ? h('div', { class: 'kv' }, h('span', null, 'Minimal buyurtma'), h('span', null, String(p.min_order_amount))) : null,
    editable ? h('div', { class: 'bank-actions' }, toggle, del) : null);
}

async function render() {
  const editable = can('PRICING_UPDATE');
  const body = h('div', { class: 'cards-body' });
  const formSlot = h('div', { class: 'form-slot' });

  function paint(list) {
    clear(body);
    const items = Array.isArray(list) ? list : [];
    if (!items.length) { body.appendChild(emptyNote("Hozircha promo-kodlar yo'q")); return; }
    body.appendChild(h('ul', { class: 'bank-list' }, items.map((p) => promoCard(p, editable, load))));
  }
  async function load() {
    try {
      paint(await api('/api/admin/promocodes'));
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }
  function openForm() {
    clear(formSlot);
    formSlot.appendChild(promoForm(() => { clear(formSlot); load(); }, () => clear(formSlot)));
  }

  paint(await api('/api/admin/promocodes'));
  return h('div', { class: 'view promos' },
    pageHead('Promo-kodlar', editable ? h('button', { type: 'button', class: 'btn btn-primary', onclick: openForm }, "Promo-kod qo'shish") : null),
    formSlot, body);
}

registerView('promos', render);
