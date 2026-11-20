// Sovg'alar: the real Telegram gift catalog (synced from the bot), with the bot's Stars balance.
// GET /api/admin/gifts, POST /api/admin/gifts/sync, PATCH /api/admin/gifts/{id}
// (PRICING_READ / PRICING_UPDATE). Gift ids are strings (large Telegram ids) and never become
// numbers. Titles and emoji come from Telegram, so everything goes through h() as plain text.
import { h, clear, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, emptyNote, inlineError, badge, toggleSwitch, formatDate } from './ui.js';
import { field, readField, numberProblem, formError } from '../forms.js';

const giftUrl = (id) => `/api/admin/gifts/${encodeURIComponent(id)}`;
const stars = (n) => `${n} ⭐`;

function balanceCard(data, editable, onSync) {
  const bal = data.bot_star_balance;
  const sync = editable
    ? h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, 'Sinxronlash')
    : null;
  if (sync) {
    sync.addEventListener('click', () => runAction({
      button: sync,
      key: 'gifts:sync',
      call: () => api('/api/admin/gifts/sync', { method: 'POST' }),
      success: (r) => `Katalog yangilandi: qo'shildi ${(r && r.added) || 0}, yangilandi ${(r && r.updated) || 0}`,
    }).then((ok) => { if (ok) onSync(); }));
  }
  return h('div', { class: 'card gift-balance' },
    h('b', null, `Botning Stars balansi: ${bal === null || bal === undefined ? "noma'lum" : stars(bal)} · zaxirada: ${stars(data.reserved_stars || 0)}`),
    data.low_balance
      ? h('p', { class: 'gift-warning', role: 'alert' }, "Botda Stars kam: sovg'alarni yetkazib bo'lmasligi mumkin. Balansni to'ldiring.")
      : null,
    data.last_sync_error ? h('p', { class: 'field-error', role: 'alert' }, `Oxirgi sinxronlash xatosi: ${data.last_sync_error}`) : null,
    h('div', { class: 'bank-top' },
      h('span', { class: 'muted small' }, data.last_sync_at ? `Oxirgi sinxronlash: ${formatDate(data.last_sync_at)}` : 'Hali sinxronlanmagan'),
      sync));
}

function giftCard(g, editable, reload) {
  const id = String(g.id);
  const titleField = field({ label: 'Nomi', name: `title_${id}`, value: g.title || '', attrs: editable ? { maxlength: '64' } : { disabled: true } });
  const overrideField = field({
    label: "Narx tuzatish (so'm)", name: `override_${id}`, type: 'number', min: 0, step: 'any',
    value: g.price_override_uzs ?? '', attrs: editable ? { placeholder: 'Avtomatik' } : { disabled: true },
  });
  const error = formError();
  const name = g.name || g.title || stars(g.star_count);

  const sw = toggleSwitch(`${name} sotuvda`, g.enabled, !editable, async (el) => {
    const next = el.getAttribute('aria-checked') !== 'true';
    const ok = await runAction({
      button: el,
      key: `gift:${id}`,
      confirm: next
        ? { title: "Sovg'a yoqilsinmi?", text: `${name} do'konda ko'rsatiladi.`, confirmLabel: 'Yoqish' }
        : { title: "Sovg'a o'chirilsinmi?", text: `${name} do'konda ko'rsatilmaydi.`, confirmLabel: "Ha, o'chirish" },
      call: () => api(giftUrl(id), { method: 'PATCH', body: { enabled: next } }),
      success: next ? "Sovg'a yoqildi" : "Sovg'a o'chirildi",
    });
    if (ok) reload();
  });

  const saveTitle = h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, 'Nomni saqlash');
  saveTitle.addEventListener('click', async () => {
    const next = readField(titleField) || null;
    if ((g.title || null) === next) { error.show("Nom o'zgarmagan"); return; }
    error.hide();
    const ok = await runAction({
      button: saveTitle,
      key: `gift:${id}`,
      confirm: { title: "Nom o'zgartirilsinmi?", text: `${name} → ${next || `${stars(g.star_count)} (avtomatik)`}.`, confirmLabel: 'Ha, saqlash' },
      call: () => api(giftUrl(id), { method: 'PATCH', body: { title: next } }),
      success: 'Nom saqlandi',
    });
    if (ok) reload();
  });

  const saveOverride = h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, 'Narxni saqlash');
  saveOverride.addEventListener('click', async () => {
    const next = readField(overrideField);
    const prev = g.price_override_uzs ?? null;
    if (next !== null) {
      const problem = numberProblem(next, { label: 'Narx', min: 0 });
      if (problem) { error.show(problem); return; }
    }
    if (next === prev) { error.show("Narx o'zgarmagan"); return; }
    error.hide();
    const ok = await runAction({
      button: saveOverride,
      key: `gift:${id}`,
      confirm: {
        title: "Sotuv narxi o'zgartirilsinmi?",
        text: `${name}: ${formatSom(g.price_uzs)} → ${next === null ? 'avtomatik narx (tannarx + marja)' : formatSom(next)}. Yangi narx darhol mijozlarga qo'llanadi.`,
        confirmLabel: 'Ha, saqlash',
        danger: true,
      },
      call: () => api(giftUrl(id), { method: 'PATCH', body: { price_override_uzs: next } }),
      success: 'Narx saqlandi',
    });
    if (ok) reload();
  });

  return h('li', { class: 'card bank-card gift-card' },
    h('div', { class: 'bank-top' },
      h('b', null, `${g.emoji || ''} ${name}`.trim()),
      h('span', { class: 'gift-badges' },
        g.is_premium ? badge('Premium', 'pending') : null,
        g.available ? null : badge("Telegram'da yo'q", 'cancel'),
        g.is_limited ? badge(`Qoldiq: ${g.remaining_count ?? '?'}`, 'pending') : null)),
    h('div', { class: 'kv' }, h('span', null, 'Stars'), h('span', null, stars(g.star_count))),
    h('div', { class: 'kv' }, h('span', null, 'Sotuv narxi'), h('b', null, formatSom(g.price_uzs))),
    h('div', { class: 'kv' }, h('span', null, 'Tannarxi'), h('span', null, formatSom(g.cost_uzs))),
    h('div', { class: 'gift-edit' }, titleField, editable ? saveTitle : null),
    h('div', { class: 'gift-edit' }, overrideField, editable ? saveOverride : null),
    error,
    h('div', { class: 'bank-actions' }, h('span', { class: 'muted small' }, g.enabled ? 'Sotuvda' : "O'chirilgan"), sw));
}

async function render() {
  const editable = can('PRICING_UPDATE');
  const body = h('div', { class: 'cards-body' });

  function paint(data) {
    clear(body);
    const d = data || {};
    const items = Array.isArray(d.gifts) ? d.gifts : [];
    body.appendChild(balanceCard(d, editable, load));
    if (!items.length) {
      body.appendChild(emptyNote("Hozircha sovg'alar yo'q", editable ? "«Sinxronlash» tugmasi bilan Telegram katalogini yuklang." : null));
      return;
    }
    body.appendChild(h('ul', { class: 'bank-list' }, items.map((g) => giftCard(g, editable, load))));
  }
  async function load() {
    try {
      paint(await api('/api/admin/gifts'));
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }

  paint(await api('/api/admin/gifts'));
  return h('div', { class: 'view gifts' }, pageHead("Sovg'alar"), body);
}

registerView('gifts', render);
