// Mandatory-subscription gate (/api/gate/check). Shown alone, without the nav, until
// every channel is joined; "Tekshirish" re-checks and calls onPassed.
import { h, clear, icon } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { gateBlocked } from '../store.js';
import { showToast } from '../../shared/state.js';

function openChannel(link) {
  const url = String(link || '');
  if (url.startsWith('https://t.me/')) tg.openTelegramLink(url);
  else tg.openLink(url); // https only; anything else is ignored
}

function channelRow(c) {
  const passed = Boolean(c.passed);
  return h('div', { class: passed ? 'gate-channel passed' : 'gate-channel' },
    h('span', { class: 'gate-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'gate-title' }, String(c.title || c.display_name || 'Kanal')),
    passed
      ? h('span', { class: 'status status-ok' }, icon('check'), "A'zo")
      : h('button', {
        type: 'button', class: 'btn btn-primary btn-sm',
        onclick: () => { tg.haptic('light'); openChannel(c.link); },
      }, "Obuna bo'lish"));
}

export async function gateScreen(channels, onPassed) {
  const list = h('div', { class: 'gate-list' });
  const msg = h('p', { class: 'field-error', role: 'alert', hidden: true });
  function render(chs) {
    clear(list);
    for (const c of Array.isArray(chs) ? chs : []) if (c && typeof c === 'object') list.appendChild(channelRow(c));
  }
  function setMsg(text) {
    msg.textContent = text || '';
    if (text) msg.removeAttribute('hidden');
    else msg.setAttribute('hidden', '');
  }

  let checking = false;
  const checkBtn = h('button', {
    type: 'button', class: 'btn btn-primary btn-block',
    onclick: async () => {
      if (checking) return;
      checking = true;
      checkBtn.disabled = true;
      setMsg(null);
      try {
        const res = await api('/api/gate/check');
        if (gateBlocked(res)) {
          tg.haptic('error');
          render(res.channels);
          setMsg("Siz hali obuna bo'lmagansiz. Barcha kanallarga obuna bo'ling.");
        } else {
          tg.haptic('success');
          showToast('Obuna tasdiqlandi');
          if (typeof onPassed === 'function') await onPassed();
        }
      } catch (err) {
        setMsg((err && err.message) || 'Tekshirishda xatolik');
      } finally {
        checking = false;
        checkBtn.disabled = false;
      }
    },
  }, icon('refresh'), 'Tekshirish');

  render(channels);
  return h('div', { class: 'state state-full gate' },
    h('div', { class: 'state-icon' }, icon('telegram')),
    h('h1', { class: 'state-title' }, "Davom etish uchun obuna bo'ling"),
    h('p', { class: 'state-text' }, "Ilovadan foydalanish uchun quyidagi kanal(lar)ga obuna bo'lishingiz shart."),
    list,
    msg,
    checkBtn);
}
