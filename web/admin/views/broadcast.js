// Broadcast: audience segment, message (text + photo URL, or a channel post), inline buttons.
// GET /api/admin/broadcast/latest-draft + /status (BROADCAST_CREATE), POST /api/admin/broadcast (BROADCAST_SEND).
// The latest draft is the post the admin forwarded to the bot; it is restored into the text field on
// open. The backend exposes no audience-size endpoint, so the confirm names the audience segment;
// the real recipient count is shown from the send response.
// The text is previewed raw through h() text: Telegram may parse HTML tags in it, we never do.
import { h, clear } from '../../shared/dom.js';
import { api, ApiError } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, chips, iconButton, formatDate } from './ui.js';
import { field, readField, formError } from '../forms.js';

export const SEGMENTS = [
  ['all', 'Barchasi', 'Barcha foydalanuvchilarga'],
  ['non_buyers', 'Hali xarid qilmaganlar', 'Hali xarid qilmagan foydalanuvchilarga'],
  ['active', 'Faol mijozlar', 'Faol mijozlarga'],
  ['referral', 'Referal orqali kelganlar', 'Referal orqali kelgan foydalanuvchilarga'],
];
const MODES = [['write', 'Matn / rasm'], ['post_link', 'Telegram postidan']];
const URL_OK = /^(https?:\/\/|tg:\/\/)\S+$/i;

function buttonRows(onChange) {
  const list = h('div', { class: 'disc-list' });
  const rows = [];
  const read = () => rows
    .map((r) => ({ text: String(r.t.value || '').trim(), url: String(r.u.value || '').trim() }))
    .filter((b) => b.text || b.url);
  const add = () => {
    const t = h('input', { class: 'input', name: 'btn_text', placeholder: 'Tugma matni', autocomplete: 'off', 'aria-label': 'Tugma matni' });
    const u = h('input', { class: 'input', name: 'btn_url', placeholder: 'https://t.me/...', autocomplete: 'off', 'aria-label': 'Tugma havolasi' });
    const row = { t, u };
    const del = h('button', { type: 'button', class: 'btn btn-danger btn-sm', 'aria-label': "Tugmani o'chirish" }, "O'chirish");
    const el = h('div', { class: 'disc-row' }, t, u, del);
    del.addEventListener('click', () => { rows.splice(rows.indexOf(row), 1); el.remove(); onChange(); });
    t.addEventListener('input', onChange);
    u.addEventListener('input', onChange);
    rows.push(row);
    list.appendChild(el);
    onChange();
  };
  const root = h('div', { class: 'field' },
    h('span', { class: 'field-label' }, 'Inline tugmalar (xabar ostidagi havolalar)'),
    list,
    h('div', null, iconButton("Tugma qo'shish", null, add, 'btn btn-secondary btn-sm')));
  root.read = read;
  return root;
}

async function render() {
  const canSend = can('BROADCAST_SEND');
  let segment = 'all';
  let mode = 'write';
  let draftId = null;
  let draftText = null;
  const error = formError();

  const textArea = h('textarea', {
    class: 'input', name: 'text', rows: '5', placeholder: 'Xabar matnini kiriting...', 'aria-label': 'Xabar matni',
    style: { minHeight: '120px', padding: '10px', resize: 'vertical' },
  });
  const photo = field({ label: 'Rasm havolasi (ixtiyoriy)', name: 'photo_url', attrs: { placeholder: 'https://...' } });
  const postLink = field({ label: 'Kanal postining havolasi', name: 'post_link', attrs: { placeholder: 'https://t.me/kanal/123' } });
  const forward = field({ label: "Forward sifatida yuborish (kanal nomi ko'rinadi)", name: 'forward_mode', type: 'checkbox', value: false });
  const draftNote = h('p', { class: 'muted small', hidden: true });

  const previewText = h('p', { class: 'preview-text', style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '0' } });
  const previewMeta = h('div', { class: 'preview-meta muted small' });
  const previewBtns = h('div', { class: 'row-actions' });
  const preview = h('div', { class: 'card bank-card', 'aria-label': 'Xabar ko\'rinishi' },
    h('h3', { class: 'section-title' }, "Ko'rinish"),
    previewText, previewMeta, previewBtns,
    h('p', { class: 'muted small' }, "Telegram xabardagi HTML teglarni (<b>, <i>, <a>) o'zi qayta ishlaydi; bu yerda matn xom holda ko'rsatiladi."));

  const buttons = buttonRows(() => repaint());
  const writeBox = h('div', { class: 'cards-section' },
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Xabar matni'), textArea),
    draftNote, photo);
  const postBox = h('div', { class: 'cards-section' }, postLink, forward);

  const segChips = chips(SEGMENTS.map(([v, l]) => [v, l]), segment, (v) => { segment = v; }, 'chips');
  const modeChips = chips(MODES, mode, (v) => { mode = v; syncMode(); repaint(); }, 'chips');

  function syncMode() {
    if (mode === 'write') { writeBox.removeAttribute('hidden'); postBox.setAttribute('hidden', ''); } else { postBox.removeAttribute('hidden'); writeBox.setAttribute('hidden', ''); }
  }
  function repaint() {
    previewText.textContent = mode === 'write' ? (textArea.value || '') : `Telegram post: ${readField(postLink) || '—'}`;
    previewMeta.textContent = mode === 'write' && readField(photo) ? `Rasm: ${readField(photo)}` : '';
    clear(previewBtns);
    for (const b of buttons.read()) previewBtns.appendChild(h('span', { class: 'pill' }, b.text || '…'));
  }
  textArea.addEventListener('input', repaint);
  photo.querySelector('input').addEventListener('input', repaint);
  postLink.querySelector('input').addEventListener('input', repaint);

  function applyDraft(d) {
    if (!d) return false;
    if (d.text) {
      textArea.value = String(d.text);
      draftId = d.id;
      draftText = String(d.text);
      draftNote.textContent = `Botga yuborilgan oxirgi post yuklandi${d.created_at ? ` (${d.created_at})` : ''}.`;
    } else {
      draftId = null;
      draftText = null;
      draftNote.textContent = "Botdagi oxirgi post media (matnsiz): uni \"Telegram postidan\" rejimi orqali yuboring.";
    }
    draftNote.removeAttribute('hidden');
    repaint();
    return true;
  }
  async function loadDraft(manual) {
    try {
      const res = await api('/api/admin/broadcast/latest-draft');
      if (res && res.has_draft && res.draft) { applyDraft(res.draft); if (manual) return true; } else if (manual) {
        draftNote.textContent = "Botga hali post yuborilmagan. Botga istalgan postni yuboring.";
        draftNote.removeAttribute('hidden');
      }
    } catch { /* a missing draft never blocks writing a message */ }
    return false;
  }

  // Result + delivery status.
  const report = h('div', { class: 'card bank-card', hidden: true, role: 'status' });
  // After a timeout / network failure the server may still have started the broadcast, so the send
  // stays locked until a status refresh succeeds (or the view is re-entered).
  let sendLocked = false;
  function lockSend() {
    sendLocked = true;
    send.setAttribute('disabled', '');
    clear(report);
    report.removeAttribute('hidden');
    report.appendChild(h('h3', { class: 'section-title' }, "Natija noma'lum — Holat bo'limida tekshiring"));
    report.appendChild(h('p', { class: 'muted small' }, "So'rov javobsiz qoldi; xabar yuborilgan bo'lishi mumkin. \"Holatni yangilash\" tugmasini bosing."));
  }
  async function loadStatus() {
    try {
      const s = await api('/api/admin/broadcast/status');
      if (!s) return;
      if (sendLocked) {
        sendLocked = false;
        if (canSend) send.removeAttribute('disabled');
      }
      clear(report);
      report.removeAttribute('hidden');
      report.appendChild(h('h3', { class: 'section-title' }, s.is_running ? 'Yuborilmoqda...' : 'Oxirgi broadcast'));
      for (const [label, v] of [['Jami', s.total], ['Yetkazildi', s.sent], ['Bloklagan', s.blocked], ['Xatolar', s.failed]]) {
        report.appendChild(h('div', { class: 'kv' }, h('span', null, label), h('b', null, String(v ?? 0))));
      }
      if (s.completed_at) report.appendChild(h('p', { class: 'muted small' }, formatDate(s.completed_at)));
    } catch { /* status is informational */ }
  }

  function collect() {
    const btns = buttons.read();
    for (const b of btns) {
      if (!b.text || !b.url) return { problem: "Tugma matni va havolasini to'liq kiriting" };
      if (!URL_OK.test(b.url)) return { problem: 'Tugma havolasi https://, http:// yoki tg:// bilan boshlanishi kerak' };
    }
    const body = { segment, mode, buttons: btns.length ? btns : null, forward_mode: false };
    if (mode === 'write') {
      const text = String(textArea.value || '').trim();
      if (!text) return { problem: 'Xabar matnini kiriting' };
      const photoUrl = readField(photo);
      if (photoUrl && !/^https?:\/\//i.test(photoUrl)) return { problem: 'Rasm havolasi http(s):// bilan boshlanishi kerak' };
      body.text = text;
      body.photo_url = photoUrl || null;
      if (draftId && text === String(draftText || '').trim()) { body.draft_id = draftId; body.mode = 'postbot'; }
    } else {
      const link = readField(postLink);
      if (!link || !link.includes('t.me/')) return { problem: 'Kanal postining havolasini kiriting (https://t.me/...)' };
      body.post_link = link;
      body.forward_mode = Boolean(readField(forward));
    }
    return { body };
  }

  const send = h('button', { type: 'button', class: 'btn btn-primary' }, 'Yuborish');
  if (!canSend) send.setAttribute('disabled', '');
  send.addEventListener('click', async () => {
    if (sendLocked) return;
    const { body, problem } = collect();
    if (problem) { error.show(problem); return; }
    error.hide();
    const audience = (SEGMENTS.find(([v]) => v === segment) || SEGMENTS[0])[2];
    let result = null;
    let unknown = false;
    const ok = await runAction({
      button: send,
      key: 'broadcast:send',
      confirm: {
        title: 'Xabar yuborilsinmi?',
        text: `${audience} xabar yuboriladi. Yuborilgan xabarni qaytarib bo'lmaydi.`,
        confirmLabel: 'Ha, yuborish',
        danger: true,
      },
      call: async () => {
        try {
          result = await api('/api/admin/broadcast', { method: 'POST', body });
          return result;
        } catch (err) {
          if (err instanceof ApiError && err.status === 0) unknown = true;
          throw err;
        }
      },
      success: (r) => (r && r.message) || 'Broadcast boshlandi',
    });
    if (unknown) { lockSend(); return; }
    if (ok) {
      clear(report);
      report.removeAttribute('hidden');
      report.appendChild(h('h3', { class: 'section-title' }, 'Broadcast boshlandi'));
      report.appendChild(h('p', null, `Qabul qiluvchilar soni: ${result && result.recipients_count !== undefined ? result.recipients_count : '—'} ta.`));
      report.appendChild(h('p', { class: 'muted small' }, "Yakunlangach bot sizga hisobot yuboradi."));
    }
  });

  syncMode();
  repaint();
  await loadDraft(false);
  await loadStatus();

  return h('div', { class: 'view broadcast' },
    pageHead('Broadcast'),
    h('div', { class: 'card card-form' },
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Auditoriya'), segChips),
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Xabar turi'), modeChips),
      writeBox, postBox,
      h('div', null, iconButton('Botdagi oxirgi postni olish', 'refresh', () => loadDraft(true), 'btn btn-secondary btn-sm')),
      buttons,
      h('p', { class: 'muted small' }, 'Xabarlar soniyasiga ~25-30 ta tezlikda yuboriladi.'),
      error,
      canSend ? null : h('p', { class: 'muted small' }, "Yuborish uchun ruxsat yo'q"),
      h('div', { class: 'form-actions' }, send)),
    preview,
    report,
    h('div', null, iconButton('Holatni yangilash', 'refresh', () => loadStatus(), 'btn btn-secondary btn-sm')));
}

registerView('broadcast', render);
