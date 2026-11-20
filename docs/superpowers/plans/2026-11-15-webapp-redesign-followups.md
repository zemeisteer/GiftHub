# Web App redesign — qolgan ishlar (follow-ups)

Branch: `feat/webapp-redesign`. Hamma bosqichlar va yakuniy review tugagan; quyidagilar ataylab keyinga qoldirilgan.

## Inson tekshiruvi kerak (merge'dan oldin)
- Haqiqiy Telegram ichida tekshirish: `ENVIRONMENT=production` bilan `tunnel.py` → @gifthubuzbot orqali `/app` va `/admin`: MainButton, openLink, CSP ostida `telegram-web-app.js` inline style qo'shmasligi, nusxa olish (clipboard), to'lov va to'ldirish oqimi.

## Backend xavfsizlik muammolari (oldindan mavjud, bu branch tegmagan)
- `/api/v1` foydalanuvchi route'lari autentifikatsiyasiz: `POST /orders/checkout` body'dagi `user_id`ga ishonadi (boshqaning hamyonidan yechish), `/orders/{id}/receipt` (cost/margin/tx), `/timeline`, `/buy-again-details`, `GET/POST/DELETE /recipients` (`user_id` query). Alohida hotfix sessiyasi taklif qilingan.
- `GET /api/admin/fragment/settings` `tonapi_key`ni ochiq qaytaradi — `has_tonapi_key` bo'lishi kerak.
- Backend adminga o'zini o'chirishga ruxsat beradi; `POST /api/admin/admins` rolni tekshirmaydi (UI bloklaydi).
- `/api/products` sovg'alar `cost_uzs`ini login'siz qaytaradi.
- `/api/promo/apply` commit qilmaydi → `balance_bonus` kodlar qo'shilgandek ko'rinib bekor bo'ladi.
- Legacy sovg'a buyurtmasi nom bo'yicha 60 000 fallback narx (yangi ilova id yuboradi).
- `tunnel.js` (Node) development himoyasisiz — `tunnel.py` dagi tekshiruvni chetlab o'tadi.
- ~~**Sovg'alar haqiqatda yetkazilmaydi** (50 Stars sifatida ketardi).~~ YOPILDI: sovg'alar endi haqiqiy katalogdan (`telegram_gifts`) sotiladi va Bot API `sendGift` orqali yetkaziladi (`app/services/gift_delivery.py`). Haqiqiy sinash: README "Sovg'alarni haqiqiy sinash".
- Sovg'a: kanal/guruhga yuborish yo'q (`sendGift` `chat_id`), faqat shaxsga. Stars/Premium ham faqat foydalanuvchi `@username`iga ketadi.
- Sovg'a: stiker/animatsiya rasmi katalogda yo'q (faqat emoji), sovg'a bilan matn (`text`) yuborilmaydi.
- Premium'ni `giftPremiumSubscription` (Bot API) orqali yetkazish ko'rib chiqilmagan.
- **Stars/Premium hamon yolg'on "bajarildi" bo'lib belgilanadi:** `app/services/fragment.py` dagi Fragment/TON yetkazish simulyatsiya (soxta); haqiqiy yetkazish yo'q.
- Qayta buyurtma ikki marta yechishi mumkin: `orders.py` `create_order` + `debit_balance` (idempotentlik yo'q).
- `last_sync_error` xom exception matnini saqlashi mumkin (ichki ma'lumot chiqib ketishi).
- Botdagi do'kon: `cb_recipient_self` eskirgan `recipient_id`ni tozalamaydi.
- Idempotentlikda `request_hash` hech qachon solishtirilmaydi (bir xil kalit, boshqa tana qabul qilinadi).
- `test_postgres_concurrency` beqarorligi (pastga qarang) sovg'a oqimlari testlariga ham ta'sir qilishi mumkin.
- Fragment raqamli Telegram ID'ni qabul qiladimi — tasdiqlanmagan (`@username`siz odam tanlanganda ID yuboriladi).

## Backend imkoniyat yetishmasliklari
- `/api/orders/create` idempotency yo'q → `/api/v1/orders/checkout` + `Idempotency-Key`ga o'tish (hozir timeout'da "holat noma'lum" ko'rsatiladi).
- `/api/admin/stats` davr (period) filtrini qo'llamaydi — KPI'lar umumiy.
- CSV eksport filtrsiz (oxirgi 1000 ta).
- Broadcast oldidan qabul qiluvchilar sonini beradigan endpoint yo'q.
- Sovg'a katalogiga yangi sovg'a qo'shish endpoint'i yo'q (eski UI qattiq kodlangan ro'yxatdan qo'shardi) — release notes'ga.
- Admin "Qaytarish" `/status cancel` orqali (legacy parity); `/refund` (sabab bilan) ishlatilmaydi.
- `manual-fulfill` `ORDERS_UPDATE` (support roli ham) — qattiqroq ruxsat ko'rib chiqilsin.

## Frontend mayda ishlar
- Narx tasdiqlashda chegirmalar faqat soni bilan ko'rsatiladi (old→new qiymatlar emas).
- Xizmat tahriri tasdiqlashida narxdan boshqa o'zgarishlar ko'rsatilmaydi.
- Maxsus Stars miqdori kiritish to'lov ketayotganda bloklanmaydi.
- Kanallar polling'i ko'rinishdan chiqqandan keyin ≤5 s davomida taymer saqlanadi.
- `confirm` singletoni timeline modal ustida ochilishi mumkin; Esc ikkalasini yopadi.
- `/static` test fayl bloki katta-kichik harfga sezgir (`path.lower()` qo'shish).
- README'dagi `/docs` havolasini `/openapi.json`ga almashtirish.
- Guard: `<a/onclick>` (bo'shliqsiz) holatini ushlamaydi; `style` obyekt qiymatlari tekshirilmaydi.
- Node ≥ 20.19 (linkedom bog'liqliklari) README'da qayd etilmagan.
- `tests/integration/test_postgres_concurrency.py` beqaror: haqiqiy lokal Postgres'da ishlaydi, foydalanuvchi ID'larini vaqtdan oladi va ma'lumotlarni tozalamaydi. To'liq ishga tushirishda ba'zan har xil testlari yiqiladi, yolg'iz ishga tushirganda o'tadi.
