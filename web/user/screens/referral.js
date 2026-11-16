// Referral: personal invite link (legacy format https://t.me/<bot>?start=ref_<user id>) and stats.
import { h, icon, formatSom } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { tg } from '../../shared/tg.js';
import { appState } from '../store.js';
import { renderError, showToast, copyText } from '../../shared/state.js';

// The legacy app's default botUsername, used when /api/bot-info is unavailable.
const DEFAULT_BOT = 'gifthubuzbot';
const BOT_RX = /^[A-Za-z][A-Za-z0-9_]{3,31}$/;
let botName = null;

async function botUsername() {
  if (botName) return botName;
  try {
    const res = await api('/api/bot-info');
    const u = res && typeof res.username === 'string' ? res.username.replace(/^@/, '') : '';
    if (BOT_RX.test(u)) botName = u;
  } catch { /* default below */ }
  return botName || DEFAULT_BOT;
}

const num = (v) => (v !== null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null);

export function referralLink(bot, userId) {
  return `https://t.me/${bot}?start=ref_${userId}`;
}

export async function referralScreen() {
  const user = appState.user || {};
  const uid = Number(user.id);
  if (!Number.isSafeInteger(uid)) return renderError('Foydalanuvchi aniqlanmadi', null);
  const [bot, stats] = await Promise.all([
    botUsername(),
    api('/api/referrals/analytics').catch(() => null),
  ]);
  const link = referralLink(bot, uid);
  const s = stats && typeof stats === 'object' ? stats : {};
  const invited = num(s.total_referrals) ?? num(user.referrals_count) ?? 0;
  const earned = num(s.total_earned) ?? num(user.referral_earnings) ?? 0;
  const buyers = num(s.purchasing_referrals);
  const rate = num(s.commission_rate);

  const input = h('input', {
    type: 'text', name: 'ref_link', class: 'field-input', readonly: true, value: link,
    'aria-label': 'Taklif havolasi',
  });
  input.value = link;
  const hint = h('p', { class: 'field-hint', hidden: true }, 'Havolani belgilab, qo\'lda nusxa oling');

  const stat = (value, label) => h('div', { class: 'stat-card' },
    h('span', { class: 'stat-val' }, value), h('span', { class: 'stat-lbl' }, label));

  return h('div', { class: 'referral-page' },
    h('h1', { class: 'page-title' }, "Do'stlarni taklif qiling"),
    h('section', { class: 'ref-card' },
      h('div', { class: 'state-icon' }, icon('users')),
      h('p', { class: 'state-text' }, rate !== null && rate > 0
        ? `Do'stlaringiz xaridlaridan ${rate}% bonus oling`
        : "Do'stlaringiz xaridlaridan bonus oling"),
      h('div', { class: 'field-row' },
        input,
        h('button', {
          type: 'button', class: 'btn btn-primary',
          onclick: async () => {
            tg.haptic('light');
            if (await copyText(link, input)) {
              hint.setAttribute('hidden', '');
              showToast('Nusxa olindi');
            } else {
              hint.removeAttribute('hidden');
            }
          },
        }, icon('copy'), 'Nusxa olish')),
      hint),
    h('div', { class: 'stat-row' },
      stat(String(invited), 'Taklif qilinganlar'),
      buyers !== null ? stat(String(buyers), 'Xarid qilganlar') : null,
      stat(formatSom(earned), 'Bonus')));
}
