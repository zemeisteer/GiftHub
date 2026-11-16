// Shared by "Kanallar" and "Majburiy obuna": both are views of the one ChannelRequirement resource.
// GET /api/admin/channels (SETTINGS_READ); POST .../{id}/type, .../{id}/toggle, .../{id}/confirm,
// DELETE .../{id} (SETTINGS_UPDATE). Channel titles and links are admin text: h() text only.
import { h } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { can, runAction, badge, toggleSwitch, switchOn, setSwitch } from './ui.js';
import { setSelect } from '../forms.js';

export const REQ_TYPES = [
  ['ordinary', 'Oddiy kanal'],
  ['join_request', "Zayavka (so'rov)"],
  ['group', 'Guruh'],
  ['external', 'Tashqi havola'],
];
export const typeLabel = (t) => (REQ_TYPES.find(([v]) => v === t) || [null, String(t || '')])[1];

export const canEditChannels = () => can('SETTINGS_UPDATE');

export async function fetchChannels() {
  const list = await api('/api/admin/channels');
  return Array.isArray(list) ? list : [];
}

// Same heuristics as the server (which re-applies them for "ordinary"), used only as a hint.
export function detectType(link) {
  const l = String(link || '').trim();
  if (!l) return null;
  if (l.includes('/+') || l.includes('joinchat') || l.startsWith('+')) return 'join_request';
  if (l.startsWith('http') && !l.includes('t.me/') && !l.includes('telegram.me/')) return 'external';
  if (l.includes('/c/') || l.toLowerCase().includes('group') || l.toLowerCase().includes('guruh')) return 'group';
  if (l.startsWith('@') || l.includes('t.me/')) return 'ordinary';
  return null;
}

export function typeSelect(value, label, onChange, extraClass = '') {
  const sel = h('select', { class: `input ${extraClass}`.trim(), 'aria-label': label },
    REQ_TYPES.map(([v, text]) => h('option', { value: v }, text)));
  setSelect(sel, REQ_TYPES.some(([v]) => v === value) ? value : 'ordinary');
  if (onChange) sel.addEventListener('change', () => onChange(sel.value));
  return sel;
}

const idUrl = (c, tail = '') => `/api/admin/channels/${encodeURIComponent(c.id)}${tail}`;

// Active/inactive channel. opts: { editable, reload, showType, showDelete }
export function channelCard(c, { editable, reload, showType = true, showDelete = true }) {
  const lock = `channel:${c.id}`;
  const head = h('div', { class: 'bank-top' },
    h('b', null, c.title || c.username_or_link),
    badge(c.is_active ? 'Faol' : 'Nofaol', c.is_active ? 'ok' : 'cancel'));
  const sw = toggleSwitch(`${c.title || c.username_or_link} majburiy obuna`, c.is_active, !editable, async (el) => {
    const next = !switchOn(el);
    const ok = await runAction({
      button: el,
      key: lock,
      confirm: next
        ? { title: 'Obuna sharti yoqilsinmi?', text: `${c.title || c.username_or_link} uchun obuna yana majburiy bo'ladi.`, confirmLabel: 'Yoqish' }
        : { title: "Obuna sharti o'chirilsinmi?", text: `Foydalanuvchilar ${c.title || c.username_or_link} ga a'zo bo'lmasdan ham foydalana oladi.`, confirmLabel: "Ha, o'chirish", danger: true },
      call: () => api(idUrl(c, '/toggle'), { method: 'POST' }),
      success: 'Kanal holati yangilandi',
    });
    if (ok) { setSwitch(el, next); reload(); }
  });
  const rows = [
    h('div', { class: 'kv' }, h('span', null, 'Havola'), h('span', { class: 'mono' }, c.username_or_link)),
  ];
  if (showType) {
    const sel = typeSelect(c.req_type, 'Shart turi', null);
    if (!editable) sel.setAttribute('disabled', '');
    sel.addEventListener('change', async () => {
      const prev = c.req_type;
      const ok = await runAction({
        button: sel,
        key: lock,
        call: () => api(idUrl(c, '/type'), { method: 'POST', body: { req_type: sel.value } }),
        success: 'Shart turi yangilandi',
      });
      if (ok) c.req_type = sel.value;
      else setSelect(sel, prev);
    });
    rows.push(h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Shart turi'), sel));
  } else {
    rows.push(h('div', { class: 'kv' }, h('span', null, 'Shart turi'), h('span', null, typeLabel(c.req_type))));
  }
  const actions = h('div', { class: 'bank-actions' }, h('span', { class: 'method-name' }, 'Majburiy'), sw);
  if (showDelete && editable) {
    const del = h('button', { type: 'button', class: 'btn btn-danger btn-sm', 'aria-label': "Kanalni o'chirish" }, "O'chirish");
    del.addEventListener('click', async () => {
      const ok = await runAction({
        button: del,
        key: lock,
        confirm: {
          title: "Kanal o'chirilsinmi?",
          text: `${c.title || c.username_or_link} majburiy obunadan butunlay olib tashlanadi.`,
          confirmLabel: "Ha, o'chirish",
          danger: true,
        },
        call: () => api(idUrl(c), { method: 'DELETE' }),
        success: "Kanal o'chirildi",
      });
      if (ok) reload();
    });
    actions.appendChild(del);
  }
  return h('li', { class: 'card bank-card' }, head, rows, actions);
}

// Channel the bot was added to as admin, waiting for the admin to pick the condition type.
export function detectedCard(c, { editable, reload }) {
  const lock = `channel:${c.id}`;
  const sel = typeSelect(c.req_type, "Majburiy a'zolik turi", null);
  const ready = h('button', { type: 'button', class: 'btn btn-primary btn-sm' }, 'Tayyor');
  ready.addEventListener('click', async () => {
    const ok = await runAction({
      button: ready,
      key: lock,
      call: () => api(idUrl(c, '/confirm'), { method: 'POST', body: { req_type: sel.value } }),
      success: 'Kanal faollashtirildi',
    });
    if (ok) reload();
  });
  const cancel = h('button', { type: 'button', class: 'btn btn-danger btn-sm' }, 'Bekor qilish');
  cancel.addEventListener('click', async () => {
    const ok = await runAction({
      button: cancel,
      key: lock,
      confirm: { title: 'Kanal bekor qilinsinmi?', text: `${c.title || c.username_or_link} ro'yxatdan olib tashlanadi.`, confirmLabel: 'Ha, bekor qilish', danger: true },
      call: () => api(idUrl(c), { method: 'DELETE' }),
      success: 'Kanal olib tashlandi',
    });
    if (ok) reload();
  });
  if (!editable) { ready.setAttribute('disabled', ''); cancel.setAttribute('disabled', ''); sel.setAttribute('disabled', ''); }
  return h('li', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, c.title || c.username_or_link), badge('Bot admin qilingan', 'ok')),
    h('div', { class: 'kv' }, h('span', null, 'Havola'), h('span', { class: 'mono' }, c.username_or_link)),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, "Qanday majburiy a'zolik?"), sel),
    h('div', { class: 'bank-actions' }, cancel, ready));
}
