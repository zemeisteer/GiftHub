// Hash router. Patterns: "#/", "#/orders", "#/product/:id".
import { clear } from './dom.js';

function compile(pattern) {
  const names = [];
  const src = pattern.replace(/[.*+?^${}()|[\]\\]/g, (c) => (c === ':' ? c : '\\' + c)).replace(/:([A-Za-z_]\w*)/g, (_, n) => {
    names.push(n);
    return '([^/]+)';
  });
  return { rx: new RegExp(`^${src}$`), names };
}

export function createRouter(routes, outlet, options = {}) {
  const table = Object.entries(routes).map(([pattern, handler]) => ({ ...compile(pattern), handler }));
  let token = 0;
  let rendered = null;

  function match(hash) {
    const path = hash.split('?')[0];
    for (const r of table) {
      const m = r.rx.exec(path);
      if (!m) continue;
      const params = {};
      try {
        r.names.forEach((n, i) => { params[n] = decodeURIComponent(m[i + 1]); });
      } catch {
        return null;
      }
      return { handler: r.handler, params };
    }
    return null;
  }

  async function render() {
    const hash = location.hash || '#/';
    const found = match(hash);
    if (!found) {
      if (hash === '#/') return undefined;
      location.replace('#/');
      return render();
    }
    rendered = hash;
    const mine = ++token;
    clear(outlet);
    let node;
    try {
      node = await found.handler(found.params);
    } catch (err) {
      if (mine !== token) return undefined;
      if (typeof options.onError !== 'function') throw err;
      node = options.onError(err);
    }
    if (mine !== token) return undefined;
    if (node) outlet.appendChild(node);
    return undefined;
  }

  function onHashChange() {
    if ((location.hash || '#/') === rendered) return undefined;
    return render();
  }

  return {
    start() {
      globalThis.addEventListener('hashchange', onHashChange);
      return render();
    },
    go(hash) {
      if (location.hash !== hash) location.hash = hash;
      return render();
    },
  };
}
