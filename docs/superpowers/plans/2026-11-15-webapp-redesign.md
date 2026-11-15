# Web App va Admin panel qayta dizayni — amalga oshirish rejasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/app` (foydalanuvchi, B · Do'kon uslubi) va `/admin` sahifalarini xavfsiz, yengil, fayllarga bo'lingan oddiy JS bilan qayta yozish va server tomondagi xavfsizlik bo'shliqlarini yopish.

**Architecture:** FastAPI `web/` papkasini `/static` sifatida beradi; `/app` va `/admin` faqat skelet `index.html` qaytaradi. Frontend ES modullar (build'siz): umumiy `web/shared/*` (DOM, API, Telegram o'rami, tokenlar) ustiga ikki ilova hash-router bilan quriladi. Barcha DOM `h()` orqali — `innerHTML` va inline handler'lar yo'q, bu qat'iy CSP'ga imkon beradi.

**Tech Stack:** Python 3.11 / FastAPI / pytest + httpx; vanilla ES2020 modullar; Node 22 `node --test` + `linkedom` (faqat testlar uchun devDependency); Telegram WebApp SDK.

**Spec:** `docs/superpowers/specs/2026-11-15-webapp-redesign-design.md`

## Global Constraints

- Build bosqichi yo'q; Dockerfile o'zgarmaydi. Node faqat lokal testlar uchun.
- `web/` ichida taqiqlangan: `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, inline `on*=` atributlari, inline `<script>` (src'siz) va `<style>`.
- Tashqi skript faqat `https://telegram.org/js/telegram-web-app.js`. Twemoji va boshqa CDN'lar olib tashlanadi.
- CSP (aynan shu qiymat): `default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org`
- Qo'shimcha sarlavhalar: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
- `ENVIRONMENT` default — `production`. Dev-fallback (`auth_user_id`, `X-Auth-User-Id`) faqat `development`/`test`.
- Narx va summa faqat serverdan; frontend hisoblamaydi.
- Aksent rangi: yorug'da `#16a34a`, qorong'ida `#22c55e`. Boshqa ranglar Telegram `themeParams`dan.
- Til: o'zbek (lotin). Pul formati: `10 350 so'm` (minglik ajratuvchi — oddiy bo'sh joy).
- Birinchi yuklash ≤ 60 KB (shriftlarsiz, siqilmagan); `backdrop-filter` ishlatilmaydi.
- Mavjud API endpoint'lari va javob formatlari o'zgarmaydi (Task 1–2 dagi xavfsizlik o'zgarishlaridan tashqari). Javob shakllarini eski `web/user/index.html` / `web/admin/index.html` dan o'qing — ular o'chirilguncha manba sifatida qoladi.

## Review Focus

1. Telegram ismi yoki username'da HTML (`<img src=x onerror=alert(1)>`) — har ikki ilovada matn sifatida ko'rinadi, ishga tushmaydi. (Task 3 `h()` testi; Task 9 users view testi.)
2. Sahifa Telegram'dan tashqarida ochilsa (`initData` bo'sh) — bo'sh ekran emas, "Ilovani @gifthubuzbot ichida oching" xabari. (Task 5 testi.)
3. Sekin yoki uzilgan internet — skeleton, 15 s dan keyin xato matni va "Qayta urinish" tugmasi; ekran qotmaydi. (Task 4 `api()` timeout testi; Task 5 holat testi.)
4. "To'lash" ikki marta tez bosilsa — faqat bitta `/api/orders/create` so'rovi. (Task 6 testi.)
5. Admin ruxsati yo'q bo'limni hash orqali ochsa (`#/admins`) — 403 da "Bu bo'lim uchun ruxsatingiz yo'q", menyuda bo'lim ko'rinmaydi. (Task 8 testi.)

---

## Fayl xaritasi

```
app/core/config.py              # ENVIRONMENT default
app/web/auth.py                 # dev-fallback faqat development/test
app/web/server.py               # static mount, security headers, CORS, docs
app/web/security_headers.py     # NEW: middleware
tunnel.py                       # development rejimida ishga tushmaydi
scripts/check_frontend.py       # NEW: taqiqlangan API'lar qidiruvi
package.json                    # devDependencies: linkedom; scripts.test
web/shared/dom.js  api.js  tg.js  router.js  tokens.css  icons.svg
web/shared/*.test.mjs
web/user/index.html  app.css  app.js  screens/{home,product,orders,referral,profile,topup,gate}.js
web/admin/index.html admin.css admin.js nav.js confirm.js views/*.js
tests/unit/test_env_defaults.py  tests/unit/test_frontend_guard.py
tests/e2e/test_security_headers.py
```

---

### Task 1: Production-by-default va dev-fallback himoyasi

**Files:**
- Modify: `app/core/config.py:15`, `app/web/auth.py:49-60`, `tunnel.py` (`main()` boshida), `tests/conftest.py` (eng tepada), `.env.example`
- Test: `tests/unit/test_env_defaults.py`

**Interfaces:**
- Produces: `settings.ENVIRONMENT` default `"production"`; `tunnel.ensure_not_development() -> None` (`SystemExit(1)` agar development).

- [ ] **Step 1: Failing testlar**

```python
def test_environment_defaults_to_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    from app.core.config import Settings
    assert Settings(_env_file=None).ENVIRONMENT == "production"

async def test_auth_user_id_rejected_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/user/me", params={"auth_user_id": 1})
    assert r.status_code == 401

def test_tunnel_refuses_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    with pytest.raises(SystemExit):
        tunnel.ensure_not_development()
```

- [ ] **Step 2:** `pytest tests/unit/test_env_defaults.py -v` → 3 FAIL.
- [ ] **Step 3:** `config.py` default'ni `"production"` qiling. `tests/conftest.py` boshida (importlardan oldin) `os.environ.setdefault("ENVIRONMENT", "test")`. `tunnel.py` ga `ensure_not_development()` qo'shing va `main()` boshida chaqiring; xabar: `"[X] ENVIRONMENT=development: dev-kirish ochiq. Tunnelni faqat ENVIRONMENT=production bilan oching."`. `.env.example` ga `ENVIRONMENT=development` qatorini izoh bilan qo'shing. Lokal `.env` ga ham `ENVIRONMENT=development` qo'shing (git'ga kirmaydi).
- [ ] **Step 4:** `pytest -q` → hammasi PASS (67 + 3).
- [ ] **Step 5:** Commit: `fix(security): production-by-default env and tunnel guard`

### Task 2: Xavfsizlik sarlavhalari, CORS, docs, static

**Files:**
- Create: `app/web/security_headers.py`
- Modify: `app/web/server.py:17-30` (FastAPI(...), CORS), `:76-95` (`/app`, `/admin`)
- Test: `tests/e2e/test_security_headers.py`

**Interfaces:**
- Produces: `add_security_headers(app: FastAPI) -> None`; `CSP_POLICY: str` (Global Constraints'dagi qiymat); `/static/...` → `web/...` (`Cache-Control: public, max-age=86400`); `ASSET_VERSION: str` (git qisqa SHA, bo'lmasa server ishga tushgan vaqt) — `/app` va `/admin` `index.html` dagi `{{v}}` ni shu qiymatga almashtirib beradi (`/static/user/app.js?v={{v}}`), shunda deploy'dan keyin eski kesh ishlatilmaydi; `index.html` o'zi `Cache-Control: no-cache`.

- [ ] **Step 1: Failing testlar**

```python
async def test_app_page_has_csp_and_nosniff(client):
    r = await client.get("/app")
    assert r.headers["content-security-policy"] == CSP_POLICY
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"

async def test_static_served_with_cache(client):
    r = await client.get("/static/shared/tokens.css")
    assert r.status_code == 200 and "max-age=86400" in r.headers["cache-control"]

async def test_cors_rejects_foreign_origin(client):
    r = await client.get("/api/products", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers

async def test_index_has_versioned_assets_and_no_cache(client):
    r = await client.get("/app")
    assert "{{v}}" not in r.text and f"?v={ASSET_VERSION}" in r.text
    assert r.headers["cache-control"] == "no-cache"

def test_docs_disabled_in_production():
    assert build_app(environment="production").docs_url is None
```

- [ ] **Step 2:** Testlarni ishga tushiring → FAIL.
- [ ] **Step 3:** Middleware'ni yozing (barcha javoblarga sarlavhalar). CORS: `allow_origins=[origin(WEB_APP_URL)]` (sxema+host), `allow_credentials=False`. `docs_url`/`openapi_url` = `None` production'da (`build_app` — `server.py` dagi app yaratishni funksiyaga ajrating, `app = build_app(settings.ENVIRONMENT)`). `app.mount("/static", StaticFiles(directory=BASE_DIR/"web"))` + cache sarlavhasi. `web/shared/tokens.css` ni bo'sh `:root{}` bilan yarating (Task 4 to'ldiradi).
- [ ] **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5:** Commit: `feat(security): CSP, security headers, strict CORS, static mount`

### Task 3: `dom.js` va frontend qo'riqchisi

**Files:**
- Create: `web/shared/dom.js`, `web/shared/dom.test.mjs`, `scripts/check_frontend.py`, `tests/unit/test_frontend_guard.py`
- Modify: `package.json` (`"devDependencies": {"linkedom": "^0.18.5"}`, `"scripts": {"test": "node --test web/"}`)

**Interfaces:**
- Produces (ES module `web/shared/dom.js`):
  - `h(tag: string, attrs?: object|null, ...children: (Node|string|number|null|false|array)[]) -> HTMLElement` — `attrs.on<Event>` funksiya bo'lsa `addEventListener`; `class`, `style` (obyekt), `dataset`, boshqalar `setAttribute`. `href`/`src` `safeUrl` orqali. Satr bolalar — text node.
  - `clear(el: Element) -> Element`
  - `formatSom(n: number|string) -> string` → `"10 350 so'm"`
  - `safeUrl(u: string) -> string|null` — faqat `https:` yoki `/` bilan boshlangan nisbiy.
- `scripts/check_frontend.py`: `find_violations(root: Path) -> list[str]` (`"fayl:qator: sabab"`), CLI `exit 1` agar bo'lsa.

- [ ] **Step 1: Failing testlar** (`dom.test.mjs`, `linkedom` bilan global `document` o'rnatiladi)

```js
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
test('formatSom', () => { assert.equal(formatSom(10350), "10 350 so'm"); assert.equal(formatSom(0), "0 so'm"); assert.equal(formatSom(1000000000), "1 000 000 000 so'm"); });
```

```python
def test_guard_flags_innerhtml(tmp_path):
    (tmp_path / "a.js").write_text("el.innerHTML = x")
    (tmp_path / "b.html").write_text('<button onclick="x()">')
    assert len(find_violations(tmp_path)) == 2

def test_new_frontend_is_clean():
    assert find_violations(Path("web/shared")) == []
```

- [ ] **Step 2:** `npm install && npm test` va `pytest tests/unit/test_frontend_guard.py` → FAIL.
- [ ] **Step 3:** Implement. Qo'riqchi faqat `web/shared`, `web/user`, `web/admin` dagi `.js`/`.html`/`.css` ni tekshiradi, `*.test.mjs` va eski fayllar o'chirilguncha `web/user/index.html`, `web/admin/index.html` (ro'yxat `LEGACY_EXCLUDES`) — Task 7 va Task 12 ularni ro'yxatdan olib tashlaydi.
- [ ] **Step 4:** `npm test` va `pytest -q` → PASS.
- [ ] **Step 5:** Commit: `feat(web): safe DOM helpers and frontend guard`

### Task 4: `api.js`, `tg.js`, `router.js`, tokenlar va ikonkalar

**Files:**
- Create: `web/shared/api.js`, `web/shared/tg.js`, `web/shared/router.js`, `web/shared/icons.svg`, `web/shared/api.test.mjs`, `web/shared/router.test.mjs`
- Modify: `web/shared/tokens.css`

**Interfaces:**
- `api(path: string, opts?: {method?: string, body?: object, timeoutMs?: number=15000}) -> Promise<any>` — `X-Telegram-Init-Data: tg.initData` qo'shadi; JSON yuboradi/oladi; xatoda `ApiError {status: number, message: string}` tashlaydi (`message` — server `detail`i yoki `"Internet aloqasi yo'q"` / `"Server javob bermadi"` timeout'da).
- `tg`: `initData: string`, `inTelegram: boolean`, `ready()`, `applyTheme(root: HTMLElement)` (themeParams → `--tg-bg`, `--tg-text`, `--tg-hint`, `--tg-secondary-bg` + `data-theme="dark|light"`), `mainButton(text: string, onClick: () => Promise|void)` (bosilganda progress va qayta bosishni bloklaydi, promise tugaguncha), `hideMainButton()`, `backButton(handler: (() => void)|null)`, `haptic('light'|'success'|'error')`, `openLink(url)`, `openTelegramLink(url)`, `user: {id, first_name, username}|null`.
- `createRouter(routes: Record<string, (params) => Promise<Node>>, outlet: Element) -> {start(), go(hash)}` — `"#/product/:id"` kabi pattern; noma'lum hash → `"#/"`.
- `icon(name: string) -> SVGElement` (`dom.js` ga qo'shiladi; `<use href="/static/shared/icons.svg#name">`). Ikonkalar: home, receipt, users, user, search, star, diamond, gift, plus, chevron-right, check, alert, refresh, copy, logout, settings, chart, tag, discount, speakerphone, telegram, card, heartbeat, shield.

- [ ] **Step 1: Failing testlar**

```js
test('api attaches initData header', async () => { /* fetch stub captures headers */ assert.equal(seen['X-Telegram-Init-Data'], 'query_id=1'); });
test('api times out with friendly message', async () => { await assert.rejects(api('/x', { timeoutMs: 10 }), { message: 'Server javob bermadi' }); });
test('api maps 4xx detail', async () => { await assert.rejects(api('/x'), { status: 400, message: 'Promo-kod topilmadi' }); });
test('router matches params', async () => { r.go('#/product/42'); assert.equal(lastParams.id, '42'); });
test('unknown route falls back to home', async () => { r.go('#/nope'); assert.equal(location.hash, '#/'); });
```

- [ ] **Step 2–4:** FAIL → implement → `npm test` PASS. `tokens.css`: o'lchamlar (`--r-sm 8px --r-md 12px --r-lg 16px`, `--gap 8/12/16px`), aksent (Global Constraints), Telegram ranglariga fallback'lar, `prefers-reduced-motion`.
- [ ] **Step 5:** Commit: `feat(web): api client, telegram wrapper, router, tokens, icons`

### Task 5: Foydalanuvchi ilovasi — qobiq va Asosiy ekran

**Files:**
- Create: `web/user/new.html` (Task 7 da `index.html` o'rniga ko'chadi), `web/user/app.css`, `web/user/app.js`, `web/user/screens/home.js`, `web/user/screens/state.js`, `web/user/home.test.mjs`
- Modify: `app/web/server.py` — vaqtincha `/app/new` → `web/user/new.html`

**Interfaces:**
- Consumes: Task 3–4 (`h`, `icon`, `formatSom`, `api`, `tg`, `createRouter`).
- Produces: `renderLoading() / renderError(message, onRetry) / renderEmpty(title, text) -> Node` (`state.js`); `homeScreen() -> Promise<Node>`; `bottomNav(active: 'home'|'orders'|'referral'|'profile') -> Node`; global `appState = {user, balance, products}` (`app.js`, `/api/user/me` va `/api/products` dan, `products` 60 s kesh).

- [ ] **Step 1: Failing testlar** (linkedom, `api` stub)

```js
test('outside Telegram shows open-in-bot message', async () => { tg.inTelegram = false; await boot(); assert.match(document.body.textContent, /@gifthubuzbot ichida oching/); });
test('home shows balance and product prices from server', async () => { /* stub products */ assert.match(text, /12 500 so'm/); assert.match(text, /10 350 so'm/); });
test('category chip filters grid', async () => { click('Premium'); assert.equal(cards().length, 3); });
test('search filters by name', async () => { type('100'); assert.deepEqual(names(), ['100 Stars']); });
test('network failure shows retry', async () => { /* api rejects */ assert.ok(find('Qayta urinish')); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Asosiy ekrandan boshqa ekran modullari router'da `import()` bilan kerak bo'lganda yuklanadi. Ekran mockup B bo'yicha: tepada balans + "To'ldirish" (→ `#/topup`), qidiruv, chiplar (Hammasi · Stars · Premium · Sovg'alar), 2 ustunli kartalar (ikonka foni: Stars `#fff4dc`, Premium `#efe9ff`, Sovg'a `#ffe9ea`; qorong'ida 20% shaffoflik), pastki menyu. Yuklanishda skeleton kartalar. `python scripts/check_frontend.py` → 0.
- [ ] **Step 5:** Brauzerda `http://127.0.0.1:8008/app/new` ni 375×812 da yorug' va qorong'i mavzuda oching; konsolda CSP xatosi yo'q. Commit: `feat(user-app): shell, home screen, states`

### Task 6: Mahsulot sahifasi va to'lov oqimi

**Files:**
- Create: `web/user/screens/product.js`, `web/user/screens/topup.js`, `web/user/product.test.mjs`

**Interfaces:**
- Consumes: `appState`, `api`, `tg.mainButton`, `renderError`.
- Produces: `productScreen({id}) -> Promise<Node>`, `topupScreen() -> Promise<Node>`.

- [ ] **Step 1: Failing testlar**

```js
test('double tap on pay sends one order', async () => { await Promise.all([pay(), pay()]); assert.equal(calls('/api/orders/create'), 1); });
test('promo applies server-returned total', async () => { /* /api/promocodes/apply returns final_price 9000 */ assert.match(mainButtonText(), /9 000 so'm/); });
test('recipient @username validated before pay', async () => { setRecipient('@a'); await pay(); assert.ok(find("Username noto'g'ri")); assert.equal(calls('/api/orders/create'), 0); });
test('insufficient balance offers top-up', async () => { /* create returns 402/400 balance */ assert.ok(find("Hamyonni to'ldirish")); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Oqim: variant/miqdor → qabul qiluvchi (O'zimga / @username / `/api/v1/recipients?user_id=` ro'yxati) → promo-kod (`/api/promocodes/apply`) → `MainButton "To'lash · N so'm"` → `/api/orders/create` → muvaffaqiyatda `tg.haptic('success')` va `#/orders`. Username qoidasi: `^@?[A-Za-z0-9_]{5,32}$`. To'ldirish: summa tanlash → `/api/wallet/topup` yoki `/api/wallet/checkout-link` → `tg.openLink(url)` (faqat `safeUrl` o'tsa).
- [ ] **Step 5:** Commit: `feat(user-app): product page and checkout flow`

### Task 7: Buyurtmalar, Referal, Profil, obuna darvozasi; eski faylni almashtirish

**Files:**
- Create: `web/user/screens/{orders,referral,profile,gate}.js`, `web/user/orders.test.mjs`
- Modify: `web/user/index.html` ← `new.html` mazmuni (eskisi o'chiriladi), `app/web/server.py` (`/app/new` olib tashlanadi), `scripts/check_frontend.py` (`LEGACY_EXCLUDES` dan `web/user/index.html` olib tashlanadi)

**Interfaces:**
- Produces: `ordersScreen()`, `referralScreen()`, `profileScreen()`, `gateScreen(channels) -> Promise<Node>`; `app.js` boot'da `/api/gate/check` — `subscribed:false` bo'lsa faqat `gateScreen`.

- [ ] **Step 1: Failing testlar**

```js
test('orders filter by status', async () => { click('Jarayonda'); assert.match(lastUrl(), /status=pending/); });
test('receipt opens for completed order', async () => { click('Chek'); assert.match(lastUrl(), /\/receipt$/); });
test('buy again pre-fills product screen', async () => { click('Yana sotib olish'); assert.equal(location.hash, '#/product/stars_100'); });
test('gate blocks app until subscribed', async () => { /* gate returns subscribed:false */ assert.ok(find('Obuna bo\'lish')); assert.equal(find('Asosiy'), null); });
test('referral link copy', async () => { click('Nusxa olish'); assert.equal(clipboard(), 'https://t.me/gifthubuzbot?start=ref_1'); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Holat filtrlari va qiymatlari eski fayldagi `activeHistoryStatus` qiymatlaridan olinadi. Referal havolasi `/api/bot-info` dagi username'dan quriladi.
- [ ] **Step 5:** Eski funksiyalar ro'yxati bo'yicha qo'lda tekshirish (Telegram ichida, tunnel orqali, `ENVIRONMENT=production`): balans, to'ldirish, Stars/Premium/Sovg'a xaridi, promo, qabul qiluvchi, tarix, chek, yana sotib olish, referal, obuna darvozasi. `python scripts/check_frontend.py` → 0. Birinchi yuklash hajmi: `index.html + app.js + app.css + shared/*` ≤ 60 KB.
- [ ] **Step 6:** Commit: `feat(user-app): orders, referral, profile, gate; replace legacy app`

### Task 8: Admin qobig'i — guruhlangan menyu, ruxsatlar, tasdiqlash oynasi

**Files:**
- Create: `web/admin/new.html`, `web/admin/admin.css`, `web/admin/admin.js`, `web/admin/nav.js`, `web/admin/confirm.js`, `web/admin/shell.test.mjs`
- Modify: `app/web/server.py` — vaqtincha `/admin/new`

**Interfaces:**
- Produces:
  - `NAV: {group: string, items: {id: string, label: string, icon: string, perm: string}[]}[]` — guruhlar va bo'limlar spec'dagi tartibda (Asosiy: dash, orders, users · Savdo: pricing, services, promos, referral · Marketing: broadcast, channels, gate · Tizim: payments, fragment, health, admins). `perm` qiymatlari `app/core/security.py` dagi `Permission` nomlari.
  - `renderNav(admin: {permissions: string[]}, active: string) -> Node`; `< 768px` da pastdan chiquvchi panel.
  - `confirmDialog({title, text, confirmLabel, danger?: boolean}) -> Promise<boolean>`
  - `registerView(id, (params) => Promise<Node>)`; 403 → `renderError("Bu bo'lim uchun ruxsatingiz yo'q")`, retry'siz.
  - Muammoli buyurtmalar soni badge: `setBadge('orders', n)`.

- [ ] **Step 1: Failing testlar**

```js
test('nav hides items without permission', () => { const n = renderNav({permissions:['ANALYTICS_READ']}, 'dash'); assert.equal(n.textContent.includes('Adminlar'), false); });
test('direct hash to forbidden view shows no-access', async () => { /* api 403 */ go('#/admins'); assert.ok(find("ruxsatingiz yo'q")); });
test('confirm resolves false on cancel', async () => { const p = confirmDialog({title:'X'}); click('Bekor qilish'); assert.equal(await p, false); });
test('all 15 legacy views present in NAV', () => assert.equal(NAV.flatMap(g => g.items).length, 15));
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Admin ma'lumoti (`permissions`) eski admin faylida qaysi endpoint'dan olinsa, o'shandan.
- [ ] **Step 5:** Commit: `feat(admin): shell with grouped permission-aware nav`

### Task 9: Bosh sahifa va asosiy bo'limlar (Buyurtmalar, Foydalanuvchilar, To'lovlar)

**Files:**
- Create: `web/admin/views/{dash,orders,users,payments}.js`, `web/admin/chart.js`, `web/admin/views.test.mjs`

**Interfaces:**
- Consumes: Task 8 `registerView`, `confirmDialog`, `setBadge`.
- Produces: `barChart(points: {label: string, value: number}[], {height?: number}) -> SVGElement`.

- [ ] **Step 1: Failing testlar**

```js
test('dash period switch refetches', async () => { click('7 kun'); assert.match(lastUrl(), /\/api\/admin\/dashboard\?period=7d/); });
test('needs-attention lists problematic orders and sets badge', async () => { assert.equal(rows('.attention').length, 3); assert.equal(badge('orders'), '3'); });
test('user name with HTML rendered as text', async () => { /* users returns first_name '<img src=x onerror=alert(1)>' */ assert.equal(document.querySelector('.users img'), null); });
test('barChart scales to max value', () => { const s = barChart([{label:'Du',value:5},{label:'Se',value:10}], {height:60}); assert.equal(bars(s)[1].getAttribute('height'), '60'); });
test('orders export downloads via link', async () => { click('Eksport'); assert.match(lastNavigated(), /\/api\/admin\/export\/orders/); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Davr parametrining aniq nomi va qiymatlari eski admin fayldagi so'rovdan olinadi (testdagi `period=7d` shu nomga moslanadi). "Qayta yuborish" amali eski fayldagi problem-orders tugmasi chaqirgan endpoint'ni ishlatadi va `confirmDialog` dan o'tadi.
- [ ] **Step 5:** Commit: `feat(admin): dashboard, orders, users, payments views`

### Task 10: Savdo bo'limlari (Narxlar, Xizmatlar, Promo-kodlar, Referal)

**Files:**
- Create: `web/admin/views/{pricing,services,promos,referral}.js`, `web/admin/forms.js`, `web/admin/sales.test.mjs`

**Interfaces:**
- Produces: `field({label, name, type, value, min?, max?, step?}) -> Node`, `readForm(form: HTMLFormElement) -> object` (raqamlar `Number`ga, bo'shlar `null`ga).

- [ ] **Step 1: Failing testlar**

```js
test('pricing save requires confirm and sends numbers', async () => { submit(); click('Saqlash'); assert.deepEqual(lastBody(), { margin_percent: 15, ton_rate_uzs: 14800 }); });
test('invalid margin blocked client-side', async () => { setField('margin_percent', '-5'); submit(); assert.ok(find("0 dan 100 gacha")); assert.equal(calls('/api/admin/pricing'), 0); });
test('promo delete asks confirmation', async () => { click('O\'chirish'); click('Bekor qilish'); assert.equal(calls('DELETE'), 0); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Maydon nomlari eski fayldagi so'rov tanalaridan.
- [ ] **Step 5:** Commit: `feat(admin): pricing, services, promos, referral views`

### Task 11: Marketing va Tizim bo'limlari

**Files:**
- Create: `web/admin/views/{broadcast,channels,gate,fragment,health,admins}.js`, `web/admin/system.test.mjs`

- [ ] **Step 1: Failing testlar**

```js
test('broadcast send needs confirm with recipient count', async () => { click('Yuborish'); assert.match(dialogText(), /\d+ foydalanuvchiga/); });
test('broadcast draft restored', async () => { assert.equal(field('text').value, 'Salom'); /* from latest-draft */ });
test('health shows degraded provider', async () => { assert.ok(find('degraded')); });
test('fragment secrets never prefilled', async () => { assert.equal(field('api_key').value, ''); assert.match(field('api_key').placeholder, /saqlangan/); });
```

- [ ] **Step 2–4:** FAIL → implement → PASS. Maxfiy maydonlar (Fragment kalitlari, karta ma'lumotlari) hech qachon qaytarib ko'rsatilmaydi — faqat "o'zgartirish" uchun bo'sh maydon.
- [ ] **Step 5:** Commit: `feat(admin): marketing and system views`

### Task 12: Admin eski faylni almashtirish va yakuniy tekshiruv

**Files:**
- Modify: `web/admin/index.html` ← `new.html`, `app/web/server.py` (`/admin/new` va `/app/new` yo'q), `scripts/check_frontend.py` (`LEGACY_EXCLUDES = []`)

- [ ] **Step 1:** Eski `web/admin/index.html` ni yangisi bilan almashtiring; `new.html` larni o'chiring.
- [ ] **Step 2:** `pytest -q` → PASS; `npm test` → PASS; `python scripts/check_frontend.py` → 0 qoidabuzarlik.
- [ ] **Step 3:** Brauzer tekshiruvi (375×812 va 1280×800, yorug' + qorong'i): har 15 bo'lim ochiladi, konsolda CSP xatosi yo'q, `grep -r "twemoji\|cdn.jsdelivr" web/` → bo'sh.
- [ ] **Step 4:** Telegram ichida, tunnel orqali, `ENVIRONMENT=production` bilan: admin bosh sahifa, bitta narx o'zgartirish (va qaytarish), muammoli buyurtma ko'rish.
- [ ] **Step 5:** Commit: `feat(admin): replace legacy admin panel`

---

## Spec qamrovi (o'z-o'zini tekshirish)

| Spec talabi | Task |
|---|---|
| Production default, dev-fallback, tunnel himoyasi | 1 |
| CSP, sarlavhalar, CORS, `/docs`, static | 2 |
| Xavfsiz render, taqiqlar, lint | 3, 12 |
| Telegram mavzusi, ikonkalar (twemoji o'rniga) | 4 |
| B · Do'kon: balans, qidiruv, chiplar, to'r, pastki menyu, holatlar | 5 |
| Xarid ≤ 3 bosish, promo, qabul qiluvchi, MainButton | 6 |
| Buyurtmalar, chek, yana sotib olish, referal, obuna darvozasi | 7 |
| Admin guruhlari, ruxsatlar, mobil panel, tasdiqlash | 8 |
| Davr, ko'rsatkichlar, "E'tibor talab qiladi", SVG grafik | 9 |
| Hamma 15 bo'lim saqlanadi | 8–11 |
| ≤ 60 KB, blur yo'q, kesh, versiyali fayllar, `import()` | 2, 5, 7 |

Spec'dan ataylab chiqarilgan: `/api/orders/create` uchun server tomonidagi idempotency kaliti (spec backend'ni o'zgartirmaydi). Ikki marta bosish frontendda bloklanadi (Task 6); server himoyasi alohida vazifa sifatida tavsiya qilinadi.
