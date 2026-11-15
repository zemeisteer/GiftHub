import { test, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

let tg;
before(async () => { ({ tg } = await import('./tg.js')); });

let calls, handlers, opened;
function installTelegram(extra = {}) {
  calls = [];
  handlers = [];
  opened = [];
  const mb = {
    setText: (t) => calls.push(['setText', t]),
    show: () => calls.push(['show']),
    hide: () => calls.push(['hide']),
    showProgress: () => calls.push(['showProgress']),
    hideProgress: () => calls.push(['hideProgress']),
    onClick: (fn) => { handlers.push(fn); calls.push(['onClick']); },
    offClick: (fn) => { const i = handlers.indexOf(fn); if (i >= 0) handlers.splice(i, 1); calls.push(['offClick']); },
  };
  globalThis.Telegram = {
    WebApp: {
      initData: '',
      MainButton: mb,
      openLink: (u) => opened.push(['link', u]),
      openTelegramLink: (u) => opened.push(['tg', u]),
      ...extra,
    },
  };
}
beforeEach(() => { tg.resetOverrides(); installTelegram(); });
afterEach(() => { tg.hideMainButton(); tg.resetOverrides(); delete globalThis.Telegram; });

const count = (name) => calls.filter((c) => c[0] === name).length;
const tick = () => new Promise((r) => setTimeout(r, 5));

test('overrides win, and a late SDK is seen', () => {
  delete globalThis.Telegram;
  assert.equal(tg.inTelegram, false);
  assert.equal(tg.initData, '');
  globalThis.Telegram = { WebApp: { initData: 'late=1', initDataUnsafe: { user: { id: 7 } } } };
  assert.equal(tg.initData, 'late=1');
  assert.equal(tg.inTelegram, true);
  assert.deepEqual(tg.user, { id: 7 });
  tg.initData = 'query_id=1';
  tg.inTelegram = false;
  assert.equal(tg.initData, 'query_id=1');
  assert.equal(tg.inTelegram, false);
});

test('mainButton: double click while pending runs onClick once, progress shown then hidden', async () => {
  let n = 0, release;
  const gate = new Promise((r) => { release = r; });
  tg.mainButton('Pay', async () => { n++; await gate; });
  const h = handlers[0];
  h(); h();
  await tick();
  assert.equal(n, 1);
  assert.equal(count('showProgress'), 1);
  assert.equal(count('hideProgress'), 0);
  release();
  await tick();
  assert.equal(count('hideProgress'), 1);
  h();
  await tick();
  assert.equal(n, 2);
});

test('mainButton: a new call offClicks the previous handler', () => {
  tg.mainButton('A', () => {});
  const first = handlers[0];
  tg.mainButton('B', () => {});
  assert.equal(count('offClick'), 1);
  assert.equal(handlers.length, 1);
  assert.notEqual(handlers[0], first);
});

test('mainButton: rejecting onClick causes no unhandled rejection', async () => {
  const seen = [];
  const onUnhandled = (e) => seen.push(e);
  process.on('unhandledRejection', onUnhandled);
  const origErr = console.error;
  console.error = () => {};
  try {
    tg.mainButton('X', async () => { throw new Error('boom'); });
    handlers[0]();
    await tick(); await tick();
  } finally {
    console.error = origErr;
    process.off('unhandledRejection', onUnhandled);
  }
  assert.equal(seen.length, 0);
  assert.equal(count('hideProgress'), 1);
});

test('mainButton: stale handler settling does not hide progress of a newer button', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  tg.mainButton('Old', async () => { await gate; });
  handlers[0]();
  await tick();
  tg.mainButton('New', () => new Promise(() => {}));
  handlers[0]();
  await tick();
  const hidesBefore = count('hideProgress');
  release();
  await tick();
  assert.equal(count('hideProgress'), hidesBefore);
});

test('mainButton: replacing a pending handler clears the spinner for the new generation', async () => {
  tg.mainButton('Old', () => new Promise(() => {}));
  handlers[0]();
  await tick();
  assert.equal(count('showProgress'), 1);
  tg.mainButton('New', () => {});
  assert.equal(count('hideProgress'), 1);
});

test('mainButton: disabled option disables the button and ignores clicks', async () => {
  let n = 0;
  globalThis.Telegram.WebApp.MainButton.disable = () => calls.push(['disable']);
  globalThis.Telegram.WebApp.MainButton.enable = () => calls.push(['enable']);
  tg.mainButton('Pay', () => { n++; }, { disabled: true });
  assert.equal(count('disable'), 1);
  await handlers[0]();
  assert.equal(n, 0);
  tg.mainButton('Pay', () => { n++; });
  assert.equal(count('enable'), 1);
  await handlers[0]();
  assert.equal(n, 1);
});

test('openLink / openTelegramLink validate urls', () => {
  tg.openLink('javascript:alert(1)');
  tg.openLink('http://a.b');
  tg.openTelegramLink('https://evil.com/x');
  tg.openTelegramLink('tg://resolve?domain=x');
  assert.deepEqual(opened, []);
  tg.openLink('https://a.b/c');
  tg.openTelegramLink('https://t.me/abc');
  assert.deepEqual(opened, [['link', 'https://a.b/c'], ['tg', 'https://t.me/abc']]);
});
