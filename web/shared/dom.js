// Single safe rendering path for the Web App. Text only, no HTML parsing.

export function safeUrl(u) {
  if (typeof u !== 'string') return null;
  const s = u.trim();
  if (s.startsWith('https://')) return s;
  if (s.startsWith('/') && !s.startsWith('//') && !s.startsWith('/\\')) return s;
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

function applyAttr(el, key, value) {
  if (value === null || value === undefined || value === false) return;
  if (/^on[A-Z]/.test(key)) {
    if (typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    return;
  }
  if (key === 'class') {
    el.className = String(value);
  } else if (key === 'style' && typeof value === 'object') {
    for (const [prop, val] of Object.entries(value)) {
      if (prop.startsWith('--')) el.style.setProperty(prop, String(val));
      else el.style[prop] = val;
    }
  } else if (key === 'dataset' && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) el.dataset[k] = String(v);
  } else if (key === 'href' || key === 'src') {
    const safe = safeUrl(String(value));
    if (safe !== null) el.setAttribute(key, safe);
  } else if (value === true) {
    el.setAttribute(key, '');
  } else {
    el.setAttribute(key, String(value));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) applyAttr(el, k, v);
  for (const c of children) appendChild(el, c);
  return el;
}
