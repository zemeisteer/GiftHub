import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { parseHTML } from 'linkedom';

let createRouter, document, outlet, listeners;

before(async () => {
  const dom = parseHTML('<!doctype html><html><body><div id="o"></div></body></html>');
  document = dom.document;
  globalThis.document = document;
  globalThis.Node = dom.Node;
  listeners = {};
  globalThis.addEventListener = (type, fn) => { listeners[type] = fn; };
  globalThis.location = {
    hash: '',
    replace(h) { this.hash = h.startsWith('#') ? h : '#' + h; },
  };
  ({ createRouter } = await import('./router.js'));
});

const tick = () => new Promise((r) => setTimeout(r, 5));
const node = (t) => { const d = document.createElement('div'); d.textContent = t; return d; };

test('router matches params and renders', async () => {
  outlet = document.createElement('div');
  let lastParams;
  const r = createRouter({
    '#/': async () => node('home'),
    '#/product/:id': async (p) => { lastParams = p; return node('p' + p.id); },
  }, outlet);
  r.go('#/product/42');
  await tick();
  assert.equal(lastParams.id, '42');
  assert.equal(outlet.textContent, 'p42');
});

test('params are decoded', async () => {
  outlet = document.createElement('div');
  let lastParams;
  const r = createRouter({ '#/': async () => node('h'), '#/s/:q': async (p) => { lastParams = p; return node('s'); } }, outlet);
  r.go('#/s/a%20b');
  await tick();
  assert.equal(lastParams.q, 'a b');
});

test('unknown route falls back to home', async () => {
  outlet = document.createElement('div');
  const r = createRouter({ '#/': async () => node('home') }, outlet);
  r.go('#/nope');
  await tick();
  assert.equal(location.hash, '#/');
  assert.equal(outlet.textContent, 'home');
});

test('start renders current hash and hashchange re-renders', async () => {
  outlet = document.createElement('div');
  const r = createRouter({ '#/': async () => node('home'), '#/orders': async () => node('orders') }, outlet);
  location.hash = '#/orders';
  r.start();
  await tick();
  assert.equal(outlet.textContent, 'orders');
  location.hash = '#/';
  listeners.hashchange();
  await tick();
  assert.equal(outlet.textContent, 'home');
});

test('stale render is ignored', async () => {
  outlet = document.createElement('div');
  let release;
  const slow = new Promise((res) => { release = res; });
  const r = createRouter({
    '#/': async () => node('home'),
    '#/slow': async () => { await slow; return node('slow'); },
  }, outlet);
  r.go('#/slow');
  r.go('#/');
  await tick();
  release();
  await tick();
  assert.equal(outlet.textContent, 'home');
});

test('handler errors go to onError', async () => {
  outlet = document.createElement('div');
  const r = createRouter({ '#/': async () => { throw new Error('boom'); } }, outlet, { onError: (e) => node('err:' + e.message) });
  r.go('#/');
  await tick();
  assert.equal(outlet.textContent, 'err:boom');
});

test('handler errors rethrown without onError', async () => {
  outlet = document.createElement('div');
  const r = createRouter({ '#/': async () => { throw new Error('boom'); } }, outlet);
  await assert.rejects(r.go('#/'), { message: 'boom' });
});
