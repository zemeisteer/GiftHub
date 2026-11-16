// Referal: bonus percent, minimum purchase and the two reward switches.
// GET /api/admin/referral (SETTINGS_READ), POST (SETTINGS_UPDATE). The POST requires all four
// fields, so all four are always sent from the form (legacy forced both booleans to true).
import { h } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead } from './ui.js';
import { field, readForm, firstProblem, formError } from '../forms.js';

async function render() {
  const editable = can('SETTINGS_UPDATE');
  const data = (await api('/api/admin/referral')) || {};
  const dis = editable ? {} : { disabled: true };
  const error = formError();
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');
  const form = h('form', { class: 'card card-form', novalidate: true },
    h('div', { class: 'form-grid' },
      field({ label: 'Bonus (%)', name: 'bonus_percent', type: 'number', value: data.bonus_percent ?? 5, min: 0, max: 100, step: 'any', attrs: dis }),
      field({ label: "Minimal xarid (so'm)", name: 'min_purchase_uzs', type: 'number', value: data.min_purchase_uzs ?? 20000, min: 0, step: 'any', attrs: dis })),
    field({ label: 'Bonus avtomatik beriladi', name: 'auto_reward', type: 'checkbox', value: data.auto_reward !== false, attrs: dis }),
    field({ label: 'Bonus uchun xarid shart', name: 'require_purchase', type: 'checkbox', value: data.require_purchase !== false, attrs: dis }),
    error,
    editable ? h('div', { class: 'form-actions' }, submit) : h('p', { class: 'muted small' }, "O'zgartirish uchun ruxsat yo'q"));

  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (!editable) return;
    const f = readForm(form);
    const body = {
      bonus_percent: f.bonus_percent,
      min_purchase_uzs: f.min_purchase_uzs,
      auto_reward: f.auto_reward,
      require_purchase: f.require_purchase,
    };
    const problem = firstProblem([
      [body.bonus_percent, { label: 'Bonus foizi', min: 0, max: 100 }],
      [body.min_purchase_uzs, { label: 'Minimal xarid', min: 0 }],
    ]);
    if (problem) { error.show(problem); return; }
    error.hide();
    await runAction({
      button: submit,
      key: 'referral',
      confirm: {
        title: 'Referal sozlamalari saqlansinmi?',
        text: `Bonus ${body.bonus_percent}%, minimal xarid ${body.min_purchase_uzs} so'm.`,
        confirmLabel: 'Ha, saqlash',
      },
      call: () => api('/api/admin/referral', { method: 'POST', body }),
      success: 'Referal sozlamalari saqlandi',
    });
  });

  return h('div', { class: 'view referral' }, pageHead('Referal'), form);
}

registerView('referral', render);
