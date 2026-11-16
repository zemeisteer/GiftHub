// Kanallar: CRUD over the mandatory-subscription channels (ChannelRequirement).
// POST /api/admin/channels {username_or_link, title|null, req_type}; the rest lives in channel-core.js.
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { registerView } from '../registry.js';
import { runAction, pageHead, emptyNote, inlineError, iconButton } from './ui.js';
import { field, readForm, formError, setSelect } from '../forms.js';
import {
  fetchChannels, channelCard, detectedCard, typeSelect, detectType, typeLabel, canEditChannels,
} from './channel-core.js';

let botUsername = '';
async function loadBotUsername() {
  if (botUsername) return botUsername;
  try {
    const data = await api('/api/bot-info');
    botUsername = (data && data.username) || '';
  } catch { /* best effort: the buttons just stay hidden */ }
  return botUsername;
}

// Opens Telegram's "add the bot as admin" picker; the new chat then shows up under "Aniqlangan".
function openAdminFlow(kind) {
  if (!/^[A-Za-z0-9_]+$/.test(botUsername)) return;
  const rights = kind === 'channel'
    ? 'post_messages+edit_messages+delete_messages+invite_users'
    : 'change_info+delete_messages+invite_users';
  const base = `https://t.me/${botUsername}?${kind === 'channel' ? 'startchannel' : 'startgroup'}=true&admin=${rights}`;
  tg.openTelegramLink(base);
}

function addForm(onSaved) {
  const error = formError();
  const hint = h('span', { class: 'muted small' });
  const sel = typeSelect('ordinary', 'Shart turi', null);
  const link = field({ label: 'Kanal @username yoki havolasi', name: 'username_or_link', attrs: { placeholder: '@kanal yoki https://t.me/...' } });
  const linkInput = link.querySelector('input');
  linkInput.addEventListener('input', () => {
    const d = detectType(linkInput.value);
    if (d) { setSelect(sel, d); hint.textContent = `Avto: ${typeLabel(d)}`; } else hint.textContent = '';
  });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, "Qo'shish");
  const form = h('form', { class: 'card card-form', novalidate: true },
    h('h3', { class: 'section-title' }, "Kanal qo'shish"),
    link,
    field({ label: 'Sarlavha (ixtiyoriy)', name: 'title' }),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Shart turi'), sel, hint),
    error,
    h('div', { class: 'form-actions' }, submit));
  form.addEventListener('submit', async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const f = readForm(form);
    if (!f.username_or_link) { error.show('Kanal @username yoki havolasini kiriting'); return; }
    error.hide();
    const ok = await runAction({
      button: submit,
      key: 'channel:new',
      call: () => api('/api/admin/channels', {
        method: 'POST',
        body: { username_or_link: f.username_or_link, title: f.title || null, req_type: sel.value },
      }),
      success: (res) => `Kanal qo'shildi: ${(res && res.title) || f.username_or_link}`,
    });
    if (ok) onSaved();
  });
  return form;
}

async function render() {
  const editable = canEditChannels();
  const body = h('div', { class: 'cards-body' });

  function paint(channels) {
    clear(body);
    const detected = channels.filter((c) => c.is_detected);
    const list = channels.filter((c) => !c.is_detected);
    if (detected.length) {
      body.appendChild(h('div', { class: 'cards-section' },
        h('h2', { class: 'section-title' }, 'Aniqlangan kanallar'),
        h('p', { class: 'muted small' }, "Bot admin qilingan kanallar: shart turini tanlab tasdiqlang."),
        h('ul', { class: 'bank-list' }, detected.map((c) => detectedCard(c, { editable, reload })))));
    }
    body.appendChild(h('div', { class: 'cards-section' },
      h('h2', { class: 'section-title' }, `Kanallar (${list.length} ta)`),
      list.length
        ? h('ul', { class: 'bank-list' }, list.map((c) => channelCard(c, { editable, reload })))
        : emptyNote("Hozircha majburiy kanallar yo'q", "Pastdagi forma yoki bot orqali qo'shing.")));
  }
  async function reload() {
    try {
      paint(await fetchChannels());
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, reload));
    }
  }

  await loadBotUsername();
  paint(await fetchChannels());
  const botButtons = editable && botUsername
    ? h('div', { class: 'row-actions' },
      iconButton('Botni kanalga qo\'shish', 'telegram', () => openAdminFlow('channel')),
      iconButton('Botni guruhga qo\'shish', 'users', () => openAdminFlow('group')))
    : null;
  return h('div', { class: 'view channels' },
    pageHead('Kanallar', iconButton('Yangilash', 'refresh', () => reload())),
    botButtons,
    editable ? addForm(() => reload()) : null,
    body);
}

registerView('channels', render);
