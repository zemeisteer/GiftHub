// Small SVG bar chart. No dependencies, text only (labels go through textContent).
import { formatSom } from '../shared/dom.js';

const NS = 'http://www.w3.org/2000/svg';
const SLOT = 48; // viewBox units per bar
const TOP = 16; // headroom for the value label
const FOOT = 20; // room for the x label

function el(tag, attrs, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function compact(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(Math.round(n));
}

// points: {label, value}[]; the tallest bar is exactly `height` units, the rest scale to it.
export function barChart(points, { height = 120 } = {}) {
  const list = Array.isArray(points) ? points : [];
  const values = list.map((p) => {
    const v = Number(p && p.value);
    return Number.isFinite(v) && v > 0 ? v : 0;
  });
  const max = Math.max(0, ...values);
  const width = Math.max(list.length, 4) * SLOT;
  const svg = el('svg', {
    class: 'bar-chart',
    viewBox: `0 0 ${width} ${height + TOP + FOOT}`,
    role: 'img',
    'aria-label': 'Savdo grafigi',
    preserveAspectRatio: 'xMidYMid meet',
  });
  list.forEach((p, i) => {
    const v = values[i];
    const h = v > 0 && max > 0 ? Math.max(2, Math.round((v / max) * height)) : 0;
    const x = i * SLOT + 8;
    const w = SLOT - 16;
    const y = TOP + height - h;
    const g = el('g', {});
    g.appendChild(el('title', {}, `${String((p && p.label) ?? '')}: ${formatSom(v)}`));
    g.appendChild(el('rect', { class: 'bar', x, y, width: w, height: h, rx: 4 }));
    if (v > 0) g.appendChild(el('text', { class: 'bar-value', x: x + w / 2, y: y - 4, 'text-anchor': 'middle' }, compact(v)));
    g.appendChild(el('text', {
      class: 'bar-label', x: x + w / 2, y: TOP + height + 14, 'text-anchor': 'middle',
    }, String((p && p.label) ?? '')));
    svg.appendChild(g);
  });
  return svg;
}
