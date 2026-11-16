// Shared form helpers for the admin sales views. Text only, through h().
import { h } from '../shared/dom.js';

// Labelled input. type 'checkbox' renders a checkbox (value = checked). Extra input attributes
// (disabled, placeholder, inputmode...) go in `attrs`.
export function field({ label, name, type = 'text', value, min, max, step, attrs = {} }) {
  const isCheck = type === 'checkbox';
  const props = { class: isCheck ? 'check' : 'input', name, type, autocomplete: 'off', ...attrs };
  if (isCheck) {
    if (value) props.checked = true;
  } else if (value !== undefined && value !== null) {
    props.value = String(value);
  }
  if (min !== undefined) props.min = String(min);
  if (max !== undefined) props.max = String(max);
  if (step !== undefined) props.step = String(step);
  if (type === 'number' && !props.inputmode) props.inputmode = 'decimal';
  const el = h('input', props);
  if (isCheck) return h('label', { class: 'field field-check' }, el, h('span', { class: 'field-label' }, label));
  return h('label', { class: 'field' }, h('span', { class: 'field-label' }, label), el);
}

function controls(form) {
  return [...form.querySelectorAll('input, select, textarea')].filter((el) => el.getAttribute('name'));
}

function readControl(el) {
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  if (type === 'checkbox') return el.checked ?? el.hasAttribute('checked');
  if (type === 'number') {
    const raw = String(el.value ?? '').trim().replace(',', '.');
    return raw === '' ? null : Number(raw);
  }
  return String(el.value ?? '').trim();
}

// Numbers become Number (empty -> null), checkboxes booleans, everything else a trimmed string.
export function readForm(form) {
  const out = {};
  for (const el of controls(form)) out[el.getAttribute('name')] = readControl(el);
  return out;
}

// Value of the single control inside a field() node, without detaching it from its form.
export function readField(node) {
  const el = node.querySelector('input, select, textarea');
  return el ? readControl(el) : null;
}

// Returns an Uzbek message when `v` breaks the rule, '' when fine.
// rule: { label, gt?, min?, max?, int? }. gt = exclusive lower bound.
export function numberProblem(v, { label, gt, min, max, int } = {}) {
  if (v === null || v === undefined || Number.isNaN(v) || !Number.isFinite(v)) return `${label} raqam bo'lishi kerak`;
  if (int && !Number.isInteger(v)) return `${label} butun son bo'lishi kerak`;
  if (gt !== undefined && max !== undefined && !(v > gt && v <= max)) return `${label} ${gt} dan katta, ${max} gacha bo'lishi kerak`;
  if (gt !== undefined && !(v > gt)) return `${label} ${gt} dan katta bo'lishi kerak`;
  if (min !== undefined && max !== undefined && (v < min || v > max)) return `${label} ${min} dan ${max} gacha bo'lishi kerak`;
  if (min !== undefined && v < min) return `${label} ${min} dan kam bo'lmasligi kerak`;
  if (max !== undefined && v > max) return `${label} ${max} dan oshmasligi kerak`;
  return '';
}

// First non-empty problem from a list of [value, rule] pairs, or ''.
export function firstProblem(checks) {
  for (const [v, rule] of checks) {
    const p = numberProblem(v, rule);
    if (p) return p;
  }
  return '';
}

// Inline error paragraph with show(msg)/hide() helpers.
export function formError() {
  const el = h('p', { class: 'field-error', role: 'alert', hidden: true });
  el.show = (msg) => { el.textContent = msg; el.removeAttribute('hidden'); };
  el.hide = () => { el.textContent = ''; el.setAttribute('hidden', ''); };
  return el;
}

// "Label: old -> new" lines for a danger confirm. changes: [[label, old, new]].
export function summarize(changes, fmt = (v) => String(v)) {
  return changes.map(([label, a, b]) => `${label}: ${fmt(a)} → ${fmt(b)}`).join('; ');
}
