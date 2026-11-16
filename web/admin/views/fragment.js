// Fragment & TON: auto-buy switches, wallet, network, minimum balance and the two secrets.
// GET /api/admin/fragment/settings (SETTINGS_READ), POST (SETTINGS_UPDATE).
// Secrets (wallet mnemonic, TonAPI key) are never prefilled or shown. The input starts empty with a
// "saqlangan" placeholder when one is stored, and the field is only sent when the admin types a new
// value: the backend (update_fragment_settings) keeps a stored value when the field is omitted.
import { h } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, badge } from './ui.js';
import { field, readForm, firstProblem, formError, summarize, setSelect } from '../forms.js';

const NETWORKS = [['mainnet', 'Mainnet'], ['testnet', 'Testnet']];

function secretField(label, name, isSet, editable) {
  return field({
    label,
    name,
    type: 'password',
    attrs: {
      placeholder: isSet ? "saqlangan (o'zgartirish uchun yangisini kiriting)" : 'kiritilmagan',
      autocomplete: 'new-password',
      ...(editable ? {} : { disabled: true }),
    },
  });
}

const shortAddr = (a) => (a && a.length > 16 ? `${a.slice(0, 8)}...${a.slice(-6)}` : a || '');

async function render() {
  const editable = can('SETTINGS_UPDATE');
  const data = (await api('/api/admin/fragment/settings')) || {};
  const dis = editable ? {} : { disabled: true };
  const error = formError();
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');

  const network = h('select', { class: 'input', name: 'network', 'aria-label': 'Tarmoq' },
    NETWORKS.map(([v, label]) => h('option', { value: v }, label)));
  setSelect(network, NETWORKS.some(([v]) => v === data.network) ? data.network : 'mainnet');
  if (!editable) network.setAttribute('disabled', '');

  const bal = Number(data.wallet_balance_ton || 0).toFixed(3);
  const status = h('div', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, 'Hamyon'),
      badge(data.is_auto_buy ? 'Avtomatik' : "Yarim avtomat", data.is_auto_buy ? 'ok' : 'pending')),
    h('div', { class: 'kv' }, h('span', null, 'Balans'), h('b', null, `${bal} TON`)),
    h('div', { class: 'kv' }, h('span', null, 'Manzil'),
      h('span', { class: 'mono' }, data.ton_wallet_address ? shortAddr(data.ton_wallet_address) : "Hamyon kiritilmagan (sinov rejimi)")),
    data.simulation_mode ? h('p', { class: 'muted small' }, 'Sinov (simulyatsiya) rejimi yoqilgan: haqiqiy to\'lov qilinmaydi.') : null);

  const form = h('form', { class: 'card card-form', novalidate: true },
    field({ label: "Avtomatik xarid (admin tasdig'isiz)", name: 'is_auto_buy', type: 'checkbox', value: Boolean(data.is_auto_buy), attrs: dis }),
    field({ label: 'Sinov (simulyatsiya) rejimi', name: 'simulation_mode', type: 'checkbox', value: Boolean(data.simulation_mode), attrs: dis }),
    field({ label: 'TON hamyon manzili', name: 'ton_wallet_address', value: data.ton_wallet_address || '', attrs: dis }),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Tarmoq'), network),
    field({ label: 'Minimal TON balans', name: 'min_ton_balance', type: 'number', value: data.min_ton_balance ?? 1, min: 0, step: 'any', attrs: dis }),
    secretField('Hamyon mnemonic (maxfiy)', 'ton_wallet_mnemonic', Boolean(data.has_mnemonic || data.ton_wallet_mnemonic_masked), editable),
    secretField('TonAPI kaliti (maxfiy)', 'tonapi_key', Boolean(data.tonapi_key), editable),
    error,
    editable ? h('div', { class: 'form-actions' }, submit) : h('p', { class: 'muted small' }, "O'zgartirish uchun ruxsat yo'q"));

  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (!editable) return;
    const f = readForm(form);
    const body = {
      is_auto_buy: f.is_auto_buy,
      simulation_mode: f.simulation_mode,
      ton_wallet_address: f.ton_wallet_address,
      network: f.network,
      min_ton_balance: f.min_ton_balance === null ? 1 : f.min_ton_balance,
    };
    // Secrets only when a new value was typed; omitted fields stay untouched on the server.
    if (f.ton_wallet_mnemonic) body.ton_wallet_mnemonic = f.ton_wallet_mnemonic;
    if (f.tonapi_key) body.tonapi_key = f.tonapi_key;
    const problem = firstProblem([[body.min_ton_balance, { label: 'Minimal balans', min: 0 }]]);
    if (problem) { error.show(problem); return; }
    error.hide();
    const yn = (v) => (v ? 'ha' : "yo'q");
    const lines = summarize([
      ['Avtomatik xarid', Boolean(data.is_auto_buy), body.is_auto_buy],
      ['Simulyatsiya', Boolean(data.simulation_mode), body.simulation_mode],
      ['Tarmoq', data.network || 'mainnet', body.network],
      ['Minimal balans', Number(data.min_ton_balance ?? 1), body.min_ton_balance],
      ...(body.ton_wallet_address !== (data.ton_wallet_address || '')
        ? [['Hamyon manzili', data.ton_wallet_address || 'kiritilmagan', body.ton_wallet_address || 'kiritilmagan']]
        : []),
    ], (v) => (typeof v === 'boolean' ? yn(v) : String(v)));
    const secrets = [
      body.ton_wallet_mnemonic ? 'hamyon mnemonic' : null,
      body.tonapi_key ? 'TonAPI kaliti' : null,
    ].filter(Boolean);
    await runAction({
      button: submit,
      key: 'fragment',
      confirm: {
        title: 'Fragment va TON sozlamalari saqlansinmi?',
        text: `${lines}.${secrets.length ? ` Yangilanadi: ${secrets.join(', ')}.` : ''} Bu to'lov va xarid jarayoniga ta'sir qiladi.`,
        confirmLabel: 'Ha, saqlash',
        danger: true,
      },
      call: async () => {
        await api('/api/admin/fragment/settings', { method: 'POST', body });
        // Secrets are not kept in the DOM after a successful save.
        form.querySelectorAll('input[type="password"]').forEach((el) => {
          if (el.value) el.setAttribute('placeholder', "saqlangan (o'zgartirish uchun yangisini kiriting)");
          el.value = '';
        });
      },
      success: 'Fragment va TON sozlamalari saqlandi',
    });
  });

  return h('div', { class: 'view fragment' }, pageHead('Fragment & TON'), status, form);
}

registerView('fragment', render);
