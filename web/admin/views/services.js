// Xizmatlar: custom services (name, category, icon, price, cost).
// GET/POST /api/admin/services, PUT/DELETE /api/admin/services/{id} (PRICING_READ / PRICING_UPDATE).
// PUT is a partial update on the backend: the edit form sends the whole record, the active
// switch sends only is_active.
import { h, clear, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, emptyNote, inlineError, badge } from './ui.js';
import { field, readForm, firstProblem, formError, summarize } from '../forms.js';

const toggleSwitch = (label, checked, disabled, onToggle) => {
  const sw = h('button', { type: 'button', role: 'switch', class: 'switch', 'aria-label': label, 'aria-checked': String(!!checked) },
    h('span', { class: 'switch-knob' }));
  if (disabled) sw.setAttribute('disabled', '');
  sw.addEventListener('click', () => onToggle(sw));
  return sw;
};

function serviceForm(service, onSaved, onCancel) {
  const s = service || { category: 'Xizmatlar', icon: '⚡', cost_uzs: 0, description: '', is_active: true };
  const error = formError();
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Saqlash');
  const form = h('form', { class: 'card card-form', novalidate: true },
    h('h3', { class: 'section-title' }, service ? 'Xizmatni tahrirlash' : "Yangi xizmat qo'shish"),
    h('div', { class: 'form-grid' },
      field({ label: 'Nomi', name: 'name', value: s.name || '' }),
      field({ label: 'Kategoriya', name: 'category', value: s.category || '' }),
      field({ label: 'Belgi (emoji)', name: 'icon', value: s.icon || '' }),
      field({ label: "Sotish narxi (so'm)", name: 'price_uzs', type: 'number', value: s.price_uzs ?? '', min: 0, step: 'any' }),
      field({ label: "Tannarxi (so'm)", name: 'cost_uzs', type: 'number', value: s.cost_uzs ?? 0, min: 0, step: 'any' }),
      field({ label: 'Tavsif', name: 'description', value: s.description || '' })),
    field({ label: 'Faol', name: 'is_active', type: 'checkbox', value: s.is_active !== false }),
    error,
    h('div', { class: 'form-actions' },
      h('button', { type: 'button', class: 'btn btn-secondary', onclick: onCancel }, 'Bekor qilish'), submit));

  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const f = readForm(form);
    const body = {
      name: f.name, category: f.category, icon: f.icon || '⚡',
      price_uzs: f.price_uzs, cost_uzs: f.cost_uzs === null ? 0 : f.cost_uzs,
      description: f.description, is_active: f.is_active,
    };
    const problem = !body.name
      ? 'Xizmat nomini kiriting'
      : firstProblem([
        [body.price_uzs, { label: 'Sotish narxi', gt: 0 }],
        [body.cost_uzs, { label: 'Tannarxi', min: 0 }],
      ]);
    if (problem) { error.show(problem); return; }
    error.hide();
    const changes = [];
    if (service) {
      if (Number(service.price_uzs) !== body.price_uzs) changes.push(['Sotish narxi', formatSom(service.price_uzs), formatSom(body.price_uzs)]);
      if (Number(service.cost_uzs) !== body.cost_uzs) changes.push(['Tannarxi', formatSom(service.cost_uzs), formatSom(body.cost_uzs)]);
    }
    const detail = service
      ? (changes.length ? summarize(changes, (v) => v) : "Narxlar o'zgarmaydi")
      : `Sotish narxi ${formatSom(body.price_uzs)}, tannarxi ${formatSom(body.cost_uzs)}`;
    const ok = await runAction({
      button: submit,
      key: service ? `service:${service.id}` : 'service:new',
      confirm: {
        title: service ? "Xizmat o'zgarishlari saqlansinmi?" : "Yangi xizmat qo'shilsinmi?",
        text: `${body.name}: ${detail}.`,
        confirmLabel: 'Ha, saqlash',
        danger: true,
      },
      call: () => api(service ? `/api/admin/services/${encodeURIComponent(service.id)}` : '/api/admin/services', {
        method: service ? 'PUT' : 'POST', body,
      }),
      success: service ? 'Xizmat yangilandi' : "Yangi xizmat qo'shildi",
    });
    if (ok) onSaved();
  });
  return form;
}

function serviceCard(s, editable, reload, edit) {
  const profit = (Number(s.price_uzs) || 0) - (Number(s.cost_uzs) || 0);
  const sw = toggleSwitch(`${s.name} faol`, s.is_active, !editable, async (el) => {
    const next = el.getAttribute('aria-checked') !== 'true';
    const ok = await runAction({
      button: el,
      key: `service:${s.id}`,
      confirm: next
        ? { title: 'Xizmat yoqilsinmi?', text: `${s.name} mijozlarga ko'rsatiladi.`, confirmLabel: 'Yoqish' }
        : { title: "Xizmat o'chirib qo'yilsinmi?", text: `${s.name} mijozlarga ko'rsatilmaydi.`, confirmLabel: "Ha, o'chirish", danger: true },
      call: () => api(`/api/admin/services/${encodeURIComponent(s.id)}`, { method: 'PUT', body: { is_active: next } }),
      success: next ? 'Xizmat yoqildi' : "Xizmat o'chirib qo'yildi",
    });
    if (ok) reload();
  });
  const del = h('button', { type: 'button', class: 'btn btn-danger btn-sm', 'aria-label': "Xizmatni o'chirish" }, "O'chirish");
  del.addEventListener('click', () => runAction({
    button: del,
    key: `service:${s.id}`,
    confirm: { title: "Xizmat o'chirilsinmi?", text: `${s.name} butunlay o'chiriladi.`, confirmLabel: "Ha, o'chirish", danger: true },
    call: () => api(`/api/admin/services/${encodeURIComponent(s.id)}`, { method: 'DELETE' }),
    success: "Xizmat o'chirildi",
  }).then((ok) => { if (ok) reload(); }));
  return h('li', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, `${s.icon || ''} ${s.name}`.trim()), badge(s.is_active ? 'Faol' : 'Nofaol', s.is_active ? 'ok' : 'cancel')),
    h('div', { class: 'muted' }, s.category || 'Xizmatlar'),
    s.description ? h('div', { class: 'muted small' }, s.description) : null,
    h('div', { class: 'kv' }, h('span', null, 'Sotish narxi'), h('b', null, formatSom(s.price_uzs))),
    h('div', { class: 'kv' }, h('span', null, 'Tannarxi'), h('span', null, formatSom(s.cost_uzs))),
    h('div', { class: 'kv' }, h('span', null, 'Foyda'), h('b', { class: 'profit' }, formatSom(profit))),
    editable ? h('div', { class: 'bank-actions' }, sw,
      h('button', { type: 'button', class: 'btn btn-secondary btn-sm', 'aria-label': 'Xizmatni tahrirlash', onclick: () => edit(s) }, 'Tahrirlash'),
      del) : null);
}

async function render() {
  const editable = can('PRICING_UPDATE');
  const body = h('div', { class: 'cards-body' });
  const formSlot = h('div', { class: 'form-slot' });

  function paint(list) {
    clear(body);
    const items = Array.isArray(list) ? list : [];
    if (!items.length) { body.appendChild(emptyNote("Hozircha xizmatlar yo'q")); return; }
    body.appendChild(h('ul', { class: 'bank-list' }, items.map((s) => serviceCard(s, editable, load, openForm))));
  }
  async function load() {
    try {
      paint(await api('/api/admin/services'));
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
  }
  function openForm(service) {
    clear(formSlot);
    formSlot.appendChild(serviceForm(service, () => { clear(formSlot); load(); }, () => clear(formSlot)));
  }

  paint(await api('/api/admin/services'));
  return h('div', { class: 'view services' },
    pageHead('Xizmatlar', editable ? h('button', { type: 'button', class: 'btn btn-primary', onclick: () => openForm(null) }, "Xizmat qo'shish") : null),
    formSlot, body);
}

registerView('services', render);
