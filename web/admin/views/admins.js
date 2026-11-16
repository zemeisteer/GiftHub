// Adminlar: list, appoint / change role (POST /api/admin/admins {identifier, role}), revoke
// (DELETE /api/admin/admins/{id}). Reads need ADMINS_READ, writes ADMINS_MANAGE (server-enforced).
// Appointing and changing a role are the same backend call (set_user_role).
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView, adminState } from '../registry.js';
import { can, runAction, pageHead, emptyNote, inlineError, badge, iconButton } from './ui.js';
import { field, readForm, formError, setSelect } from '../forms.js';

export const ROLES = [
  ['super_admin', 'Bosh administrator (barcha huquqlar)'],
  ['price_admin', 'Narx va mahsulot administratori'],
  ['support_admin', 'Yordam va buyurtmalar xodimi'],
  ['marketing_admin', 'Marketing va reklama xodimi'],
];
const roleLabel = (r) => (ROLES.find(([v]) => v === r) || [null, String(r || '')])[1];
const whoLabel = (a) => a.username || a.first_name || String(a.id);

function roleSelect(value, label) {
  const sel = h('select', { class: 'input', 'aria-label': label },
    ROLES.map(([v, text]) => h('option', { value: v }, text)));
  setSelect(sel, ROLES.some(([v]) => v === value) ? value : 'support_admin');
  return sel;
}

const roleConfirm = (who, role) => (role === 'super_admin'
  ? {
    title: 'Bosh administrator huquqi berilsinmi?',
    text: `${who} barcha huquqlarni, shu jumladan adminlarni boshqarishni oladi.`,
    confirmLabel: 'Ha, bosh admin qilish',
    danger: true,
  }
  : {
    title: 'Rol berilsinmi?',
    text: `${who}: ${roleLabel(role)}.`,
    confirmLabel: 'Ha, saqlash',
  });

function adminCard(a, manage, reload) {
  const selfId = adminState.admin && adminState.admin.id;
  const isSelf = selfId !== undefined && selfId !== null && Number(a.id) === Number(selfId);
  const who = whoLabel(a);
  const lock = `admin:${a.id}`;
  const sel = roleSelect(a.role, 'Rol');
  const rows = [
    h('div', { class: 'bank-top' }, h('b', null, a.first_name || who), badge(roleLabel(a.role), 'ok')),
    h('div', { class: 'kv' }, h('span', null, 'Username'), h('span', null, a.username || '—')),
    h('div', { class: 'kv' }, h('span', null, 'ID'), h('span', { class: 'mono' }, String(a.id))),
    a.created_at ? h('div', { class: 'kv' }, h('span', null, 'Qo\'shilgan'), h('span', null, a.created_at)) : null,
  ];
  if (!manage) return h('li', { class: 'card bank-card' }, rows);
  if (isSelf) {
    return h('li', { class: 'card bank-card' }, rows,
      h('p', { class: 'muted small' }, "Bu siz: o'zingizning rolingizni o'zgartirib yoki olib tashlab bo'lmaydi."));
  }
  const save = h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, "Rolni o'zgartirish");
  save.addEventListener('click', async () => {
    if (sel.value === a.role) return;
    const ok = await runAction({
      button: save,
      key: lock,
      confirm: roleConfirm(who, sel.value),
      call: () => api('/api/admin/admins', { method: 'POST', body: { identifier: String(a.id), role: sel.value } }),
      success: 'Rol yangilandi',
    });
    if (ok) reload();
    else setSelect(sel, a.role);
  });
  const del = h('button', { type: 'button', class: 'btn btn-danger btn-sm' }, 'Bekor qilish');
  del.addEventListener('click', async () => {
    const ok = await runAction({
      button: del,
      key: lock,
      confirm: {
        title: 'Admin huquqi bekor qilinsinmi?',
        text: `${who} oddiy foydalanuvchiga aylanadi va panelga kira olmaydi.`,
        confirmLabel: 'Ha, bekor qilish',
        danger: true,
      },
      call: () => api(`/api/admin/admins/${encodeURIComponent(a.id)}`, { method: 'DELETE' }),
      success: 'Adminlik huquqi bekor qilindi',
    });
    if (ok) reload();
  });
  return h('li', { class: 'card bank-card' }, rows,
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Rol'), sel),
    h('div', { class: 'bank-actions' }, del, save));
}

function addForm(onSaved) {
  const error = formError();
  const sel = roleSelect('support_admin', 'Rol');
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Tayinlash');
  const form = h('form', { class: 'card card-form', novalidate: true },
    h('h3', { class: 'section-title' }, 'Yangi admin tayinlash'),
    field({ label: 'Telegram ID yoki @username', name: 'identifier', attrs: { placeholder: '123456789 yoki @username' } }),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Rol'), sel),
    error,
    h('div', { class: 'form-actions' }, submit));
  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const f = readForm(form);
    if (!f.identifier) { error.show('Telegram ID yoki @username kiriting'); return; }
    error.hide();
    const ok = await runAction({
      button: submit,
      key: 'admin:new',
      confirm: roleConfirm(f.identifier, sel.value),
      call: () => api('/api/admin/admins', { method: 'POST', body: { identifier: f.identifier, role: sel.value } }),
      success: (res) => (res && res.message) || 'Yangi admin tayinlandi',
    });
    if (ok) onSaved();
  });
  return form;
}

async function render() {
  const manage = can('ADMINS_MANAGE');
  const body = h('div', { class: 'cards-body' });

  function paint(list) {
    clear(body);
    const admins = Array.isArray(list) ? list : [];
    body.appendChild(admins.length
      ? h('ul', { class: 'bank-list' }, admins.map((a) => adminCard(a, manage, load)))
      : emptyNote("Hozircha adminlar yo'q"));
  }
  async function load() {
    try {
      paint(await api('/api/admin/admins'));
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }

  paint(await api('/api/admin/admins'));
  return h('div', { class: 'view admins' },
    pageHead('Adminlar', iconButton('Yangilash', 'refresh', () => load())),
    manage ? addForm(() => load()) : null,
    body);
}

registerView('admins', render);
