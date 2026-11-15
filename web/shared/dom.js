// Single safe rendering path for the Web App. Text only, no HTML parsing.

export function safeUrl(u) {
  if (typeof u !== 'string') return null;
  // Browsers strip tab/newline inside URLs, so any control char or space is rejected.
  if (/[\x00-\x20\x7f]/.test(u)) return null;
  if (u.startsWith('https://')) return u;
  if (u.startsWith('/') && !u.startsWith('//') && !u.startsWith('/\\')) return u;
  return null;
}

export function formatSom(n) {
  const v = Math.round(Number(n));
  const num = Number.isFinite(v) ? v : 0;
  const sign = num < 0 ? '-' : '';
  const digits = String(Math.abs(num)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${sign}${digits} so'm`;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

function appendChild(el, child) {
  if (child === null || child === undefined || child === false || child === true) return;
  if (Array.isArray(child)) {
    for (const c of child) appendChild(el, c);
    return;
  }
  if (typeof child === 'string' || typeof child === 'number') {
    el.appendChild(document.createTextNode(String(child)));
    return;
  }
  if (typeof Node !== 'undefined' && child instanceof Node) {
    el.appendChild(child);
    return;
  }
  el.appendChild(document.createTextNode(String(child)));
}

const URL_ATTRS = new Set(['href', 'src', 'formaction', 'action', 'poster', 'data', 'xlink:href', 'ping', 'cite', 'background']);
const BLOCKED_ATTRS = new Set(['srcdoc']);
const BLOCKED_TAGS = new Set(['script', 'iframe', 'object', 'embed', 'style', 'frame', 'base']);

function applyAttr(el, key, value) {
  if (value === null || value === undefined || value === false) return;
  const lower = key.toLowerCase();
  if (lower.startsWith('on')) {
    if (typeof value === 'function') el.addEventListener(lower.slice(2), value);
    return;
  }
  if (BLOCKED_ATTRS.has(lower)) return;
  if (lower === 'style' && typeof value !== 'object') return;
  if (key === 'class') {
    el.className = String(value);
  } else if (lower === 'style') {
    for (const [prop, val] of Object.entries(value)) {
      if (prop.startsWith('--')) el.style.setProperty(prop, String(val));
      else el.style[prop] = val;
    }
  } else if (key === 'dataset' && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) el.dataset[k] = String(v);
  } else if (URL_ATTRS.has(lower)) {
    const safe = safeUrl(String(value));
    if (safe !== null) el.setAttribute(key, safe);
  } else if (value === true) {
    el.setAttribute(key, '');
  } else {
    el.setAttribute(key, String(value));
  }
}

const SVG_NS = 'http://www.w3.org/2000/svg';

// SVG icon from the shared sprite. Not routed through h(): that builds HTML elements.
export function icon(name) {
  if (typeof name !== 'string' || !/^[a-z0-9-]+$/.test(name)) throw new Error('icon(): invalid name');
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `/static/shared/icons.svg#${name}`);
  svg.appendChild(use);
  return svg;
}

export function h(tag, attrs, ...children) {
  if (BLOCKED_TAGS.has(String(tag).toLowerCase())) throw new Error(`h(): <${tag}> is not allowed`);
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) applyAttr(el, k, v);
  for (const c of children) appendChild(el, c);
  return el;
}
