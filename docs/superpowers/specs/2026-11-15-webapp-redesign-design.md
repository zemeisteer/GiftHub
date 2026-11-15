# GiftHub Web App va Admin panel — qayta dizayn

Sana: 2026-11-15 · Holat: tasdiqlangan (2026-11-15)

## Maqsad va sabab

Egasi foydalanuvchi Web App'ini (`/app`) va admin panelni (`/admin`) yangi dizaynga o'tkazmoqchi. Uning so'zlari bilan talablar:

- interfeys **qulay va tushunarli** bo'lsin;
- **qotib ishlamasin** (arzon telefonlarda ham tez);
- **hech kim buzib kira olmasin**;
- **HTML frontendda kod qolib ketmasin** — ya'ni maxfiy narsa yoki biznes-mantiq brauzerda bo'lmasin.

Tanlangan ko'rinish: foydalanuvchi uchun **B · Do'kon uslubi**; admin uchun guruhlangan menyu va "E'tibor talab qiladi" bloki (suhbatda chizilgan mockup).

## Maqsadlar

1. Foydalanuvchi ilovasi: narxlar birinchi ekranda; xarid 3 bosishdan oshmaydi (mahsulot → qabul qiluvchi → to'lash).
2. Admin: muammoli buyurtmalar bosh sahifaning tepasida, bir bosishda amal ("Qayta yuborish", "Ko'rish").
3. Xavfsizlik: XSS imkoniyati yo'q (`innerHTML`ga foydalanuvchi ma'lumoti tushmaydi), qat'iy CSP, production'da soxta `auth_user_id` bilan kirib bo'lmaydi.
4. Tezlik: birinchi yuklash ≤ 60 KB (gzip'dan oldin, shriftlarsiz), `backdrop-filter`/blur yo'q, 60 fps scroll.

## Maqsad emas (non-goals)

- Backend API'larini qayta loyihalash. Mavjud endpoint'lar va javob formatlari saqlanadi (faqat quyidagi xavfsizlik tuzatishlari bundan mustasno).
- Yangi biznes funksiyalar (yangi mahsulot turlari, yangi to'lov provayderi).
- Bot (aiogram) xabarlari dizayni.

## Anti-maqsadlar (texnik ishlasa ham muvaffaqiyatsizlik)

- Mavjud funksiyadan biri yo'qolsa (masalan, chek ko'rish, "qayta sotib olish", promo-kod, qabul qiluvchi tanlash, kanalga obuna tekshiruvi).
- Narx yoki summa frontendda hisoblanib, serverga ishonib yuborilsa.
- Yangi dizayn Telegram'ning qorong'i mavzusida o'qib bo'lmaydigan bo'lsa.

## Cheklovlar

- Stack: FastAPI HTML qaytaradi; build bosqichi yo'q; Docker o'zgarmaydi.
- Telegram WebApp SDK (`telegram-web-app.js`) — `telegram.org` dan yuklanadi.
- Auth: har bir API so'rovida `X-Telegram-Init-Data` sarlavhasi; server HMAC bilan tekshiradi (`app/web/auth.py`).
- Til: o'zbek (lotin).

## Yondashuvlar

| # | Yo'l | Afzalligi | Kamchiligi |
|---|------|-----------|------------|
| **1 (tanlandi)** | Oddiy JS bilan noldan qayta yozish, fayllarga bo'lingan, build'siz | Eng yengil; Docker o'zgarmaydi; qat'iy CSP mumkin | Xavfsiz render intizomi qo'lda saqlanadi |
| 2 | Preact + Vite | Kutubxona o'zi escape qiladi, komponentlar | Node build bosqichi, Dockerfile o'zgaradi |
| 3 | Faqat CSS'ni yangilash | Eng tez | 51 `innerHTML` va 112 `onclick` qoladi — xavfsizlik talabi bajarilmaydi |

Egasi 1-yo'lni tanladi. Intizom muammosini kichik `h()` yordamchi (pastda) va lint qoidasi bilan yopamiz.

## Dizayn

### Fayl tuzilishi

```
web/
  shared/
    tokens.css        # ranglar, o'lchamlar, light/dark (Telegram themeParams'dan)
    dom.js            # h(), clear(), formatSom() — yagona render yo'li
    api.js            # fetch o'rami: initData sarlavhasi, timeout, xato xabarlari
    tg.js             # Telegram SDK o'rami (ready, expand, BackButton, MainButton, haptic)
  user/
    index.html        # faqat skelet + <script type="module" src="app.js">
    app.css
    app.js            # router (hash): #/, #/catalog/:cat, #/product/:id, #/orders, #/referral, #/profile
    screens/*.js      # har ekran alohida modul
  admin/
    index.html
    admin.css
    admin.js          # router: #/dash, #/orders, #/users, #/pricing, #/promos, #/referral,
    views/*.js        #         #/broadcast, #/channels, #/payments, #/health, #/admins, ...
```

FastAPI'ga `app.mount("/static", StaticFiles(directory="web"))` qo'shiladi; `/app` va `/admin` faqat `index.html` qaytaradi.

### Xavfsiz render qoidasi

- Barcha DOM `h(tag, attrs, ...children)` orqali quriladi; matn har doim `textContent`/text node.
- `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function` va inline `on*=` atributlari **taqiqlanadi**. `scripts/check_frontend.py` ularni `web/` ichida qidiradi va testda yiqiladi.
- URL'lar (rasm, havola) faqat `https:` yoki nisbiy bo'lsa qo'yiladi.
- HTML ichida inline `<script>` va `<style>` bo'lmaydi (CSP `'self'` ularni bloklaydi) — hammasi alohida faylda.
- Emoji uchun twemoji olib tashlanadi; ikonkalar — inline SVG sprite (`web/shared/icons.svg`).

### Foydalanuvchi ilovasi (B · Do'kon uslubi)

- **Tepa:** balans + "To'ldirish" tugmasi; ostida qidiruv.
- **Toifa chiplari:** Hammasi · Stars · Premium · Sovg'alar.
- **Mahsulot to'ri:** 2 ustun, kartada ikonka, nom, narx (server bergan `price`).
- **Mahsulot sahifasi:** miqdor/variant tanlash → qabul qiluvchi (o'zim / @username / avvalgi qabul qiluvchilar `/api/v1/recipients`) → promo-kod → Telegram `MainButton` "To'lash · N so'm". Yakuniy summani server qaytaradi (`/api/promocodes/apply`, `/api/orders/create`).
- **Pastki menyu:** Asosiy · Buyurtmalar · Referal · Profil.
- **Buyurtmalar:** holat filtri, chek (`/receipt`), "Yana sotib olish" (`/buy-again-details`).
- **Obuna darvozasi:** `/api/gate/check` majburiy kanal bo'lsa, butun ekranli to'siq.
- **Mavzu:** ranglar Telegram `themeParams`dan; yashil aksent (`#16a34a` / qorong'ida `#22c55e`).
- **Holatlar:** har ekranda skeleton yuklanish, bo'sh holat va xato + "Qayta urinish".

### Admin panel

- **Menyu guruhlari:** Asosiy (Bosh sahifa, Buyurtmalar, Foydalanuvchilar) · Savdo (Narxlar, Xizmatlar, Promo-kodlar, Referal) · Marketing (Broadcast, Kanallar, Majburiy obuna) · Tizim (To'lovlar, Fragment & TON, Tizim holati, Adminlar). Hozirgi 15 bo'limning hammasi saqlanadi.
- **Bosh sahifa:** davr tanlash (Bugun/7/30 kun) → 4 ko'rsatkich → "E'tibor talab qiladi" (problem-orders) → haftalik savdo grafigi → top mahsulotlar → foyda jadvali.
- **Ma'lumot manbalari:** ko'rsatkichlar `/api/admin/dashboard`, "E'tibor talab qiladi" `/api/v1/admin/orders/problematic`, Tizim holati `/api/v1/admin/health/system`; qolgan bo'limlar hozirgi `/api/admin/*` endpoint'laridan foydalanadi (o'zgarishsiz).
- **Grafik:** hozirgidek kutubxonasiz, oddiy SVG.
- **Ruxsatlar:** menyuda faqat admin ruxsati bor bo'limlar ko'rinadi; lekin haqiqiy tekshiruv serverda (`require_permission`) qoladi.
- **Xavfli amallar** (o'chirish, broadcast yuborish, narxni o'zgartirish): tasdiqlash oynasi.
- Mobil (Telegram ichida) va desktop: < 768px da menyu pastdan chiqadigan panelga aylanadi.

### Server tomondagi xavfsizlik tuzatishlari

1. `ENVIRONMENT` default qiymati `production` bo'ladi; lokal ishlash uchun `.env` da `ENVIRONMENT=development` aniq yoziladi. Dev-fallback (`auth_user_id`, `X-Auth-User-Id`) faqat `development`/`test` da qoladi. IP bo'yicha cheklov ishonchsiz: Cloudflare tunnel orqali kelgan so'rov ham serverga `127.0.0.1` dan keladi. Shuning uchun qo'shimcha himoya: `tunnel.py` ishga tushganda `ENVIRONMENT` `development` bo'lsa ogohlantirib to'xtaydi.
2. Xavfsizlik sarlavhalari (middleware): `Content-Security-Policy: default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
3. CORS: `allow_origins=["*"]` + `allow_credentials=True` o'rniga o'z domenimiz (`WEB_APP_URL` origin'i) yoki CORS'ni butunlay o'chirish (sahifa bir xil origin'dan keladi).
4. Production'da `/docs` va `/openapi.json` o'chiriladi.
5. Tashqi skriptlar faqat `telegram.org`; boshqa CDN'lar (twemoji `@latest`) olib tashlanadi.

### Tezlik

- `backdrop-filter`, katta `box-shadow`, animatsiyali gradientlar yo'q.
- Shriftlar: bitta oila (Inter 400/500/600), `font-display: swap`; yoki tizim shrifti.
- Ekranlar `import()` bilan kerak bo'lganda yuklanadi; mahsulotlar ro'yxati 60 soniya xotirada keshlanadi.
- Statik fayllar `Cache-Control: public, max-age=86400` + fayl nomida versiya (`app.js?v=<git sha>`).

## O'tish rejasi

Yangi sahifalar `/app` va `/admin` manzillarida eskisini to'g'ridan-to'g'ri almashtiradi. Eski fayllar o'chiriladi, git tarixida qoladi. Avval xavfsizlik tuzatishlari (server), keyin foydalanuvchi ilovasi, keyin admin.

## Quruvchiga qoldirilgan qarorlar

- Aniq piksel o'lchamlari, ikonkalar to'plami, animatsiya vaqtlari.
- Ekranlar ichida modul bo'linishi.
- Grafik SVG'ning ko'rinishi.

## Mening qarorlarim (egasi tekshirishi uchun)

- `ENVIRONMENT` default'ini `production` qilish (lokal ishlashda `.env`ga bitta qator qo'shish kerak bo'ladi).
- Twemoji'ni olib tashlash, emoji o'rniga SVG ikonkalar.
- `tunnel.py` development rejimida ishga tushmasligi.
- Admin panel ham Telegram ichida ochiladi deb hisoblash (mobil + desktop tartib).
- Yashil aksent rangini saqlash (brend davomiyligi uchun).
