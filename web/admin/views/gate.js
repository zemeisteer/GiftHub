// Majburiy obuna: focused view of the same ChannelRequirement resource as "Kanallar".
// The backend has no separate gate switch: a channel enforces the subscription gate while it is
// active and not merely "detected". So this view lists exactly those channels (toggle only) and
// reports whether the gate is on at all. Adding/removing channels stays in "Kanallar".
import { h, clear } from '../../shared/dom.js';
import { registerView } from '../registry.js';
import { pageHead, emptyNote, inlineError, iconButton, badge } from './ui.js';
import { fetchChannels, channelCard, canEditChannels } from './channel-core.js';

async function render() {
  const editable = canEditChannels();
  const body = h('div', { class: 'cards-body' });

  function paint(channels) {
    clear(body);
    const enforced = channels.filter((c) => c.is_active && !c.is_detected);
    const off = channels.filter((c) => !c.is_active && !c.is_detected).length;
    body.appendChild(h('div', { class: 'card bank-card' },
      h('div', { class: 'bank-top' },
        h('b', null, 'Obuna darvozasi'),
        badge(enforced.length ? 'Yoqilgan' : "O'chiq", enforced.length ? 'ok' : 'cancel')),
      h('p', { class: 'muted small' }, enforced.length
        ? `Foydalanuvchi ${enforced.length} ta shartni bajargunicha do'konga kira olmaydi.`
        : "Faol shart yo'q: foydalanuvchilar to'siqsiz kiradi."),
      off ? h('p', { class: 'muted small' }, `Nofaol shartlar: ${off} ta`) : null,
      h('a', { class: 'link', href: '#/channels' }, "Kanallarni boshqarish")));
    body.appendChild(enforced.length
      ? h('ul', { class: 'bank-list' }, enforced.map((c) => channelCard(c, { editable, reload, showType: false, showDelete: false })))
      : emptyNote("Majburiy kanallar yo'q"));
  }
  async function reload() {
    try {
      paint(await fetchChannels());
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, reload));
    }
  }

  paint(await fetchChannels());
  return h('div', { class: 'view gate' },
    pageHead('Majburiy obuna', iconButton('Yangilash', 'refresh', () => reload())),
    body);
}

registerView('gate', render);
