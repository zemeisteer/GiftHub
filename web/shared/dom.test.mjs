import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { parseHTML } from 'linkedom';

let h, clear, formatSom, safeUrl;
before(async () => {
  const { document, Node } = parseHTML('<!doctype html><html><body></body></html>');
  globalThis.document = document;
  globalThis.Node = Node;
  ({ h, clear, formatSom, safeUrl } = await import('./dom.js'));
});

test('string child is text, never HTML', () => {
  const el = h('div', null, '<img src=x onerror=alert(1)>');
  assert.equal(el.querySelector('img'), null);
  assert.equal(el.textContent, '<img src=x onerror=alert(1)>');
});
test('on* attrs become listeners, not attributes', () => {
  let n = 0; const b = h('button', { onClick: () => n++ });
  b.click(); assert.equal(n, 1); assert.equal(b.getAttribute('onclick'), null);
});
test('unsafe href dropped', () => assert.equal(h('a', { href: 'javascript:alert(1)' }).getAttribute('href'), null));
test('formatSom', () => {
  assert.equal(formatSom(10350), "10 350 so'm");
  assert.equal(formatSom(0), "0 so'm");
  assert.equal(formatSom(1000000000), "1 000 000 000 so'm");
  assert.equal(formatSom('10350'), "10 350 so'm");
  assert.equal(formatSom(10350.6), "10 351 so'm");
});
test('safeUrl', () => {
  assert.equal(safeUrl('https://a.b/c'), 'https://a.b/c');
  assert.equal(safeUrl('/x/y'), '/x/y');
  for (const u of ['//evil.com', 'http://a.b', 'javascript:alert(1)', 'data:text/html,x', 'x/y', '', null, undefined]) {
    assert.equal(safeUrl(u), null, String(u));
  }
});
test('h attrs: class, style, dataset, booleans, nulls', () => {
  const el = h('div', { class: 'a b', style: { color: 'red' }, dataset: { id: '5' }, hidden: true, disabled: false, title: null, 'aria-label': 'x' });
  assert.equal(el.className, 'a b');
  assert.equal(el.style.color, 'red');
  assert.equal(el.dataset.id, '5');
  assert.equal(el.getAttribute('hidden'), '');
  assert.equal(el.hasAttribute('disabled'), false);
  assert.equal(el.hasAttribute('title'), false);
  assert.equal(el.getAttribute('aria-label'), 'x');
});
test('safe href/src kept, unsafe src dropped', () => {
  assert.equal(h('a', { href: '/ok' }).getAttribute('href'), '/ok');
  assert.equal(h('img', { src: 'https://x.y/z.png' }).getAttribute('src'), 'https://x.y/z.png');
  assert.equal(h('img', { src: 'data:image/png;base64,AA' }).getAttribute('src'), null);
});
test('children: arrays flattened, nulls skipped, numbers text, nodes appended', () => {
  const inner = h('b', null, 'x');
  const el = h('div', null, [['a', [1]], null, false, undefined, inner], 0);
  assert.equal(el.textContent, 'a1x0');
  assert.equal(el.querySelector('b'), inner);
});
test('clear empties element and returns it', () => {
  const el = h('div', null, 'a', h('i'));
  assert.equal(clear(el), el);
  assert.equal(el.childNodes.length, 0);
});
