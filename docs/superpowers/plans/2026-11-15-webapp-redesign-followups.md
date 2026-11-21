# Web App redesign — qolgan ishlar (follow-ups)

Branch: `feat/webapp-redesign`. Hamma bosqichlar va yakuniy review tugagan; quyidagilar ataylab keyinga qoldirilgan.

## Inson tekshiruvi kerak (merge'dan oldin)
- Haqiqiy Telegram ichida tekshirish: `ENVIRONMENT=production` bilan `tunnel.py` → @gifthubuzbot orqali `/app` va `/admin`: MainButton, openLink, CSP ostida `telegram-web-app.js` inline style qo'shmasligi, nusxa olish (clipboard), to'lov va to'ldirish oqimi.

## Backend xavfsizlik muammolari (oldindan mavjud, bu branch tegmagan)
- `/api/v1` foydalanuvchi route'lari autentifikatsiyasiz: `POST /orders/checkout` body'dagi `user_id`ga ishonadi (boshqaning hamyonidan yechish), `/orders/{id}/receipt` (cost/margin/tx), `/timeline`, `/buy-again-details`, `GET/POST/DELETE /recipients` (`user_id` query). Alohida hotfix sessiyasi taklif qilingan.
- `GET /api/admin/fragment/settings` `tonapi_key`ni ochiq qaytaradi — `has_tonapi_key` bo'lishi kerak.
- Backend adminga o'zini o'chirishga ruxsat beradi; `POST /api/admin/admins` rolni tekshirmaydi (UI bloklaydi).
- ~~`/api/products` sovg'alar `cost_uzs`ini login'siz qaytaradi.~~ YOPILDI: `gift_catalog.list_public` tannarxni qaytarmaydi (feat/telegram-gifts).
- `/api/promo/apply` commit qilmaydi → `balance_bonus` kodlar qo'shilgandek ko'rinib bekor bo'ladi.
- ~~Legacy sovg'a buyurtmasi nom bo'yicha 60 000 fallback narx.~~ YOPILDI: fallback olib tashlandi; narx faqat katalogdagi gift id bo'yicha (`pricing_service.get_gift_price`).
- `tunnel.js` (Node) development himoyasisiz — `tunnel.py` dagi tekshiruvni chetlab o'tadi.
- ~~**Sovg'alar haqiqatda yetkazilmaydi** (50 Stars sifatida ketardi).~~ YOPILDI: sovg'alar endi haqiqiy katalogdan (`telegram_gifts`) sotiladi va Bot API `sendGift` orqali yetkaziladi (`app/services/gift_delivery.py`). Haqiqiy sinash: README "Sovg'alarni haqiqiy sinash".
- Sovg'a: kanal/guruhga yuborish yo'q (`sendGift` `chat_id`), faqat shaxsga. Stars/Premium ham faqat foydalanuvchi `@username`iga ketadi.
- Sovg'a: stiker/animatsiya rasmi katalogda yo'q (faqat emoji), sovg'a bilan matn (`text`) yuborilmaydi.
- Premium'ni `giftPremiumSubscription` (Bot API) orqali yetkazish ko'rib chiqilmagan.
- ~~**Stars/Premium yolg'on "bajarildi" bo'lib belgilanadi.**~~ YOPILDI (fix/manual-fulfillment): soxta tx id olib tashlandi; Stars/Premium/xizmat buyurtmalari `manual_review` ga tushadi, xaridor «qabul qilindi», adminlar «qo'lda bajarish kerak» xabarini oladi. **Hali yo'q:** haqiqiy avtomatik TON yuborish (`send_ton_transaction` `manual=True` qaytaradi).
- ~~Qayta buyurtma ikki marta yechishi mumkin: `orders.py` `create_order` + `debit_balance`.~~ YOPILDI (fix wave): ortiqcha `debit_balance` va `transition_order_status` olib tashlandi; `create_order` yagona yechim.
- ~~`last_sync_error` xom exception matnini saqlashi mumkin.~~ YOPILDI (fix wave): `bot<id>:<token>` ko'rinishlari `bot<redacted>` bilan almashtiriladi (boshqa xom matn hamon saqlanadi).
- ~~Botdagi do'kon: `cb_recipient_self` eskirgan `recipient_id`ni tozalamaydi.~~ YOPILDI (fix wave): "O'zimga" o'z raqamli ID'ni yozadi, yangi sovg'a tanlovi qabul qiluvchini tozalaydi.
- Idempotentlikda `request_hash` hech qachon solishtirilmaydi (bir xil kalit, boshqa tana qabul qilinadi).
- `test_postgres_concurrency` beqarorligi (pastga qarang) sovg'a oqimlari testlariga ham ta'sir qilishi mumkin.
- Fragment raqamli Telegram ID'ni qabul qiladimi — tasdiqlanmagan (`@username`siz odam tanlanganda ID yuboriladi). Endi faqat Stars/Premium'ga tegishli: sovg'alar `sendGift` orqali raqamli ID bilan yuboriladi.

## Sovg'alar (feat/telegram-gifts) — yakuniy review'dan qolganlar
- `app/services/worker.py:112` `send_order_created_notification` noto'g'ri kwargs bilan chaqiriladi (TypeError) → `ORDER_CREATED_NOTIFICATION` hodisalari doim yiqiladi (oldindan mavjud).
- Admin guard (`gift_admin_conflict`) check-then-act: tekshiruv va `transition_order_status` orasida sovg'a `processing`ga o'tishi mumkin. `transition_order_status` ichida qator qulfi ostida `fulfillment_status`ni qayta tekshirish kerak.
- Sweep cutoff (5 daqiqa) va eng yomon yuborish budjeti (~240 s) bir-biriga bog'lanmagan: `sendGift`ga `request_timeout` qo'shish yoki konstantalarni bog'lash.
- `startup_gift_sync` Telegram'ga ulanib bo'lmasa worker ishga tushishini kechiktiradi (timeout/fon vazifa qilish).
- `adm_srv` cancel/link handler'lari (`app/handlers/users/admin_panel.py` ~:347, ~:397) sovg'a guard'isiz (hozir UI orqali sovg'aga yetib bo'lmaydi).
- Admin Sovg'alar narx kiritish: `type=number` "5 000"ni bo'sh deb oladi (noto'g'ri tasdiq matni), klientda 1e9 maksimum yo'q.
- Admin Sovg'alar ko'rinishini 375px kenglikda vizual tekshirish hali qilinmagan.
- Bot "qayta xarid" `fulfill_order_automated`ni to'g'ridan-to'g'ri ham chaqiradi, outbox hodisasi ham yaratiladi (ikki yo'l; sovg'a uchun `_claim`, Stars uchun dublikat tekshiruvi himoya qiladi).

## Backend imkoniyat yetishmasliklari
- `/api/orders/create` idempotency yo'q → `/api/v1/orders/checkout` + `Idempotency-Key`ga o'tish (hozir timeout'da "holat noma'lum" ko'rsatiladi).
- `/api/admin/stats` davr (period) filtrini qo'llamaydi — KPI'lar umumiy.
- CSV eksport filtrsiz (oxirgi 1000 ta).
- Broadcast oldidan qabul qiluvchilar sonini beradigan endpoint yo'q.
- ~~Sovg'a katalogiga yangi sovg'a qo'shish endpoint'i yo'q.~~ YOPILDI: katalog Telegram'dan (`getAvailableGifts`) sinxronlanadi; admin faqat yoqadi/o'chiradi va narxni o'zgartiradi (Sovg'alar bo'limi).
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
