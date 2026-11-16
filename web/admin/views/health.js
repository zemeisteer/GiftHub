// Tizim holati: GET /api/v1/admin/health/system (SETTINGS_READ), plus the failed-job queue
// GET /api/v1/admin/dlq (ORDERS_READ) with retry / resolve (ORDERS_UPDATE; resolve needs a reason >= 5 chars).
// Everything shown is server data rendered through h() text.
import { h, clear } from '../../shared/dom.js';
import { api } from '../../shared/api.js';
import { registerView } from '../registry.js';
import { can, runAction, pageHead, emptyNote, inlineError, iconButton, badge, formatDate } from './ui.js';

const GOOD = new Set(['healthy', 'operational', 'online', 'connected', 'running', 'ok']);
const toneOf = (s) => (GOOD.has(String(s || '').toLowerCase()) ? 'ok' : 'cancel');

const OVERALL = {
  healthy: ["Tizim barqaror", "Barcha asosiy komponentlar ishlayapti."],
  degraded: ["Tizim qisman pasaygan", "Ayrim xizmatlar yoki navbatlarda muammo bor."],
  critical: ['Kritik xatolik', "Asosiy bog'liqlikda uzilish aniqlandi."],
};

const kv = (label, value) => h('div', { class: 'kv' }, h('span', null, label), h('span', null, value === null || value === undefined || value === '' ? '—' : String(value)));
const ms = (v) => (v === null || v === undefined ? '—' : `${v} ms`);

function card(title, status, ...rows) {
  return h('div', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, title), status ? badge(String(status), toneOf(status)) : null),
    rows);
}

function overallBanner(d) {
  const key = String(d.overall_status || '').toLowerCase();
  const [title, text] = OVERALL[key] || ['Holat noma\'lum', ''];
  return h('div', { class: 'card bank-card', role: 'status' },
    h('div', { class: 'bank-top' }, h('b', null, title), badge(key || 'unknown', toneOf(key))),
    text ? h('p', { class: 'muted small' }, text) : null,
    d.timestamp ? h('p', { class: 'muted small' }, `Tekshirildi: ${formatDate(d.timestamp)}`) : null);
}

function providerCards(d) {
  const out = [];
  for (const [name, p] of Object.entries(d.payment_providers || {})) {
    out.push(card(name, p.status,
      kv('Yoqilgan', p.is_active === false ? "yo'q" : 'ha'), kv('Circuit', p.circuit)));
  }
  for (const [name, p] of Object.entries(d.fulfillment_providers || {})) {
    out.push(card(name, p.status,
      kv('Avtomatik xarid', p.auto_buy ? 'ha' : "yo'q"),
      kv('Simulyatsiya', p.simulation_mode ? 'ha' : "yo'q"),
      kv('Circuit', p.circuit)));
  }
  return out;
}

function dlqRow(job, canAct, reload) {
  const lock = `dlq:${job.id}`;
  const retry = h('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, 'Qayta urinish');
  retry.addEventListener('click', async () => {
    const ok = await runAction({
      button: retry,
      key: lock,
      confirm: { title: 'Job qayta urinishga qo\'yilsinmi?', text: `Job #${job.id} (${job.job_type}) qayta bajariladi.`, confirmLabel: 'Ha, qayta urinish' },
      call: () => api(`/api/v1/admin/dlq/${encodeURIComponent(job.id)}/retry`, { method: 'POST' }),
      success: 'Job qayta urinish navbatiga qo\'yildi',
    });
    if (ok) reload();
  });
  const resolve = h('button', { type: 'button', class: 'btn btn-danger btn-sm' }, 'Hal qilindi');
  resolve.addEventListener('click', async () => {
    const ok = await runAction({
      button: resolve,
      key: lock,
      confirm: {
        title: 'Job hal qilindi deb belgilansinmi?',
        text: `Job #${job.id} (${job.job_type}) navbatdan olinadi va qayta bajarilmaydi.`,
        confirmLabel: 'Ha, hal qilindi',
        danger: true,
        input: { label: 'Sabab', required: true, minLength: 5 },
      },
      call: (reason) => api(`/api/v1/admin/dlq/${encodeURIComponent(job.id)}/resolve`, { method: 'POST', body: { reason } }),
      success: 'Job hal qilindi',
    });
    if (ok) reload();
  });
  return h('li', { class: 'card bank-card' },
    h('div', { class: 'bank-top' }, h('b', null, `#${job.id} ${job.job_type}`), badge(String(job.status), job.status === 'retrying' ? 'pending' : 'cancel')),
    job.order_id ? kv('Buyurtma', `#${job.order_id}`) : null,
    kv('Urinishlar', job.attempts),
    kv('Vaqt', formatDate(job.created_at)),
    job.error_message ? h('p', { class: 'attention-reason' }, String(job.error_message)) : null,
    canAct ? h('div', { class: 'bank-actions' }, retry, resolve) : null);
}

async function render() {
  const body = h('div', { class: 'cards-body' });
  const dlqBody = h('div', { class: 'cards-body' });
  const canDlq = can('ORDERS_READ');
  const canAct = can('ORDERS_UPDATE');

  async function loadDlq() {
    if (!canDlq) return;
    try {
      const res = await api('/api/v1/admin/dlq');
      const jobs = Array.isArray(res && res.jobs) ? res.jobs : [];
      clear(dlqBody);
      dlqBody.appendChild(jobs.length
        ? h('ul', { class: 'bank-list' }, jobs.map((j) => dlqRow(j, canAct, loadDlq)))
        : emptyNote("Muvaffaqiyatsiz joblar yo'q"));
    } catch (err) {
      clear(dlqBody);
      dlqBody.appendChild(inlineError(err && err.message, loadDlq));
    }
  }

  function paint(d) {
    clear(body);
    const q = d.queue_depth || {};
    const f = d.failed_jobs || {};
    const w = d.workers || {};
    body.appendChild(overallBanner(d));
    body.appendChild(h('div', { class: 'cards-section' },
      h('h2', { class: 'section-title' }, 'Komponentlar'),
      card('Bot', (d.bot || {}).status, kv('Foydalanuvchi', (d.bot || {}).username ? `@${d.bot.username}` : ''), kv('Rejim', (d.bot || {}).mode)),
      card('Ma\'lumotlar bazasi', (d.database || {}).status, kv('Kechikish', ms((d.database || {}).latency_ms)), kv('Dvigatel', (d.database || {}).engine)),
      card('Redis', (d.redis || {}).status, kv('Kechikish', ms((d.redis || {}).latency_ms)), kv('FSM', (d.redis || {}).fsm_storage)),
      card('Worker', w.is_running ? 'running' : 'stopped',
        kv('Oxirgi signal', w.seconds_since_heartbeat === null || w.seconds_since_heartbeat === undefined ? '—' : `${w.seconds_since_heartbeat} s oldin`),
        kv('Sikllar', w.cycle_count))));
    const providers = providerCards(d);
    if (providers.length) {
      body.appendChild(h('div', { class: 'cards-section' }, h('h2', { class: 'section-title' }, "Provayderlar"), providers));
    }
    body.appendChild(h('div', { class: 'cards-section' },
      h('h2', { class: 'section-title' }, 'Navbatlar'),
      card('Navbat chuqurligi', null,
        kv('Kutayotgan outbox', q.pending_outbox_events),
        kv("Yetkazilmagan to'langan buyurtmalar", q.unfulfilled_paid_orders),
        kv('Xotiradagi navbat', q.in_memory_queue_size)),
      card('Muvaffaqiyatsiz joblar (DLQ)', null,
        kv('Tugagan', f.exhausted_jobs), kv('Qayta urinishda', f.retrying_jobs), kv('Jami faol', f.total_active_failures))));
  }

  async function load() {
    try {
      paint((await api('/api/v1/admin/health/system')) || {});
    } catch (err) {
      clear(body);
      body.appendChild(inlineError(err && err.message, load));
    }
    await loadDlq();
  }

  paint((await api('/api/v1/admin/health/system')) || {});
  await loadDlq();
  return h('div', { class: 'view health' },
    pageHead('Tizim holati', iconButton('Yangilash', 'refresh', () => load())),
    body,
    canDlq ? h('div', { class: 'cards-section' }, h('h2', { class: 'section-title' }, 'DLQ: muvaffaqiyatsiz joblar'), dlqBody) : null);
}

registerView('health', render);
