# Haqiqiy Telegram sovg'alari (`sendGift`) — dizayn

Sana: 2026-11-20 · Holat: tasdiqlash kutilmoqda

## Maqsad va sabab

Hozir sovg'a sotib olgan mijoz sovg'ani **olmaydi**: `app/services/fragment.py:267` da sovg'a buyurtmasi qabul qiluvchiga 50 ta Stars sifatida yetkazilishi kerak (`create_stars_invoice(recipient, 50)`), katalogdagi 12 ta sovg'a (Luxury Yacht, Ruby Crown...) esa Telegram'da mavjud emas va narxlari Telegram narxlariga bog'liq emas.

Egasi (tanlov: **A**) katalogni Telegram'ning haqiqiy sovg'alariga almashtirmoqchi, bot esa to'lovdan keyin ularni `sendGift` bilan qabul qiluvchiga haqiqatan yuborishi kerak.

## Maqsadlar

1. Katalog Telegram'ning `getAvailableGifts` ro'yxatidan avtomatik olinadi (yangi sovg'alar o'zi qo'shiladi).
2. Narx serverda hisoblanadi: sovg'aning Stars narxi (`star_count`) xuddi shuncha Stars sotib olish bilan bir xil (mavjud Stars narxi + ustama). Admin har sovg'aga alohida sotuv narxi qo'yishi va sovg'ani o'chirib qo'yishi mumkin.
3. To'lovdan keyin bot `sendGift(user_id, gift_id)` bilan sovg'ani yuboradi; muvaffaqiyatda buyurtma `fulfilled`, mijozga xabar boradi.
4. Muvaffaqiyatsizlikda (bot Stars balansi yetmasa, sovg'a tugagan bo'lsa, odam sovg'a qabul qilmasa) mijozning puli hamyonga qaytariladi, mijoz va adminlar xabar oladi.
5. Do'kon (Web App) va botdagi do'kon bo'limi bir xil yangi katalogdan o'qiydi.
6. Admin panelda "Sovg'alar" bo'limi: ro'yxat, narx tuzatish, yoqish/o'chirish, "Sinxronlash" tugmasi, botning Stars balansi.

## Maqsad emas (non-goals)

- Kanal va guruhga sovg'a (keyingi qadam: `chat_id` bilan yuborish, `request_chat` tanlovi, cheklangan sovg'alarni to'sish).
- Telegram stikeri rasmlari (bu bosqichda emoji + narx; rasm keyingi qadam).
- Sovg'a bilan birga matn, `pay_for_upgrade` (unikal sovg'aga yangilash), unikal sovg'alar.
- Telegram Premium'ni `giftPremiumSubscription` bilan Stars orqali yuborish.
- Botning Stars balansini to'ldirish (egasi qiladi).
- **Stars va Premium buyurtmalarining soxta yetkazilishini tuzatish** — alohida masala (pastdagi "Topilma" bo'limi).

## Anti-maqsadlar (texnik ishlasa ham muvaffaqiyatsizlik)

- Mijozdan pul olinib, sovg'a yuborilmasdan qolsa (va pul qaytarilmasa).
- Bitta buyurtma uchun sovg'a **ikki marta** yuborilsa (bot Stars'ini yo'qotadi; `sendGift` takrorlanganda xavfsiz emas).
- Mijoz ko'rgan narx bilan yechilgan narx farq qilsa (narx har doim serverda hisoblanadi).
- Botning tokeni yoki tannarx (`cost_uzs`) ochiq API javobida chiqsa.

## Cheklovlar (tekshirilgan faktlar)

- aiogram 3.31 da `send_gift(gift_id, user_id|chat_id, ...)`, `get_available_gifts()`, `get_my_star_balance()` bor (Bot API 10.3). `sendGift` `True` qaytaradi, boshqa ma'lumot bermaydi.
- `Gift`: `id`, `sticker` (emoji shu yerdan), `star_count`, `is_premium`, `total_count`/`remaining_count` (cheklanganlar uchun). Nomi yo'q.
- `sendGift` **raqamli `user_id`** talab qiladi (username emas). Qabul qiluvchi: o'zi (`appState.user.id`), "Chatdan tanlash" (ID qaytaradi), qo'lda raqamli ID, yoki `@username` — faqat botdan foydalangan odam bo'lsa (`users` jadvalidan ID topiladi). Aks holda buyurtma yaratilmaydi, aniq xabar chiqadi.
- Sovg'a narxi **botning Stars balansidan** to'lanadi (hujjatda aniq yozilmagan, lekin shunday ishlaydi deb olinadi — real sinovda tasdiqlanadi). Balansni to'ldirish usuli hujjatda yo'q.
- Xato matnlari (`BALANCE_TOO_LOW` va h.k.) hujjatlashtirilmagan: xatolar turi (`TelegramBadRequest`, `TelegramRetryAfter`, tarmoq) va matn bo'yicha tasniflanadi, noma'lumlari jurnalga yoziladi.
- Production'da sxema Alembic bilan boshqariladi: yangi jadval uchun migratsiya `0006` kerak (staging'da `create_all`).

## Yondashuvlar

| # | Yo'l | Natija |
|---|------|--------|
| **1 (tanlandi)** | Yangi `telegram_gifts` jadvali + vaqti-vaqti bilan sinxronlash | Admin yoqish/o'chirish/narx qila oladi; do'kon tez; migratsiya kerak |
| 2 | Mavjud `pricing.gifts_json` ga yozish | Migratsiya yo'q, lekin sinxronlash va admin tahriri bir-birini bosadi |
| 3 | Har safar Telegram'dan so'rash | Sekin, admin boshqaruvi yo'q, narx o'zgarishi mumkin — mos emas |

## Dizayn

### Ma'lumotlar
Jadval `telegram_gifts`: `id` (Telegram gift id, string, PK), `emoji`, `title` (admin tahrirlaydi, bo'sh bo'lsa `emoji + "N Stars"`), `star_count`, `is_limited`, `remaining_count` (null), `is_premium`, `available` (oxirgi sinxronlashda Telegram ro'yxatida bor edi), `enabled` (admin, yangi sovg'a uchun `true`), `price_override_uzs` (null), `synced_at`. `orders` ga `recipient_user_id` (BigInteger, null) qo'shiladi: sovg'a buyurtmalarida buyurtma yaratilganda aniqlangan raqamli ID. Eski `pricing.gifts_json` tegilmaydi, ishlatilmaydi; tarixdagi eski sovg'a buyurtmalari xom `item_title` bilan ko'rinadi (R6 qoidasi).

### Sinxronlash
Xizmat `gift_catalog.sync(bot)`: `getAvailableGifts` → `telegram_gifts` ga upsert; ro'yxatdan chiqqanlarga `available=false`; `is_premium` sovg'alar do'konda ko'rsatilmaydi. Ishga tushadi: worker'da taxminan soatiga bir marta (mavjud davriy tsikl yonida), admin "Sinxronlash" tugmasi, jadval bo'sh bo'lsa ishga tushishda. Har sinxronlashda `getMyStarBalance` ham saqlanadi.

### Narx va ko'rsatish
`PricingService` da sovg'a narxi: `price_override_uzs` bo'lsa shu, aks holda `calculate_stars_price(star_count)` natijasi (tannarx ham shundan). `get_authoritative_price(product_type="gift", item_title=<gift id>)` endi DB'dan o'qiydi (mavjud va yoqilgan va `available` va qoldig'i bor sovg'a bo'lmasa xato). `/api/products` ning `gifts` ro'yxati: `id`, `name`, `icon` (emoji), `price_uzs`, `type`, `stars`, `remaining` — eski maydon nomlari saqlanadi (Web App buzilmaydi); `cost_uzs` **chiqarilmaydi**.

### Buyurtma yaratish
Pul yechishdan oldin tekshiriladi: sovg'a mavjud/yoqilgan/qoldig'i bor, qabul qiluvchi ID'si aniqlanadi (yuqoridagi qoida), keshdagi bot Stars balansi `star_count` dan kam emas (noma'lum bo'lsa o'tkaziladi). Aks holda 400 va o'zbekcha tushunarli xabar, pul yechilmaydi.

### Yetkazish
`FulfillmentService` da `product_type == "gift"` bo'lsa `fragment_client` o'rniga yangi `gift_delivery.deliver(order, bot)` ishlaydi: `bot.send_gift(user_id=order.recipient_user_id, gift_id=order.item_title)`.
- **Hech qachon ikki marta yubormaslik (bitta tekshiruv nuqtasi):** `gift_delivery.deliver` ichida buyurtma `fulfillment_status = 'pending'` dan `'processing'` ga **atomik** (`UPDATE ... WHERE fulfillment_status='pending'`) o'tkaziladi va commit qilinadi, **shundan keyingina** `send_gift` chaqiriladi. Holat `pending` bo'lmasa, hech narsa yuborilmaydi. Shu tufayli barcha kirish yo'llari (worker, outbox, DLQ qayta urinishi, admin "qayta urinish", botdagi yo'l) xavfsiz bo'ladi. Admin `retry-fulfillment` sovg'a buyurtmasiga 409 qaytaradi.
- Sovg'a buyurtmalari `FulfillmentService` ning umumiy sikliga (`MAX_FULFILLMENT_RETRIES`, "fragment" circuit breaker, `retry_scheduled`, DLQ) **kirmaydi**: `fulfill_order_automated` boshida `product_type == "gift"` bo'lsa darhol `gift_delivery.deliver` ga o'tadi.
- Avtomatik qayta urinish faqat `TelegramRetryAfter` da (yuborilmaganiga ishonch bor): ko'pi bilan 2 marta, har biri ≤ 30 soniya kutish bilan; undan keyin `manual_review`.
- **Noma'lum natija** (tarmoq/timeout/noma'lum xato, yoki worker qulab `processing` da qolishi): `fulfillment_status = 'manual_review'`, buyurtmaning asosiy holati `PROCESSING` **o'zgarmaydi** (`FAILED` ga o'tkazilmaydi, chunki `FAILED → PROCESSING` qayta urinish yo'li ikki marta yuborishga olib keladi). Worker tsiklida 5 daqiqadan eski `processing` sovg'a buyurtmalari shunday `manual_review` ga o'tkaziladi va adminlarga xabar boradi. Admin faqat ikki amal qila oladi: "bajarildi deb belgilash" (`manual-fulfill`, sabab bilan; botning sovg'alar tarixini ko'rib tekshiradi) yoki qaytarish.
- **Doimiy xatolar** (`TelegramBadRequest`/`Forbidden`: balans yetmasligi, sovg'a tugagani, odam sovg'a qabul qilmasligi, noma'lum 400): buyurtma `PROCESSING` dan to'g'ridan-to'g'ri `REFUNDED` ga o'tadi va pul hamyonga qaytariladi (mavjud `order_service` qaytarish yo'li; qaytarish va holat o'zgarishi bitta tranzaksiyada). Mijozga sabab bilan xabar, adminlarga ogohlantirish (balans yetmasa alohida, Telegram'ning xom xato matni bilan).
- Muvaffaqiyat: `fulfilled`, `fragment_tx_hash` o'rniga yetkazish ma'lumoti (`fragment_payload`) ga `sendGift` yozuvi; mijozga xabar va ilova ichidagi bildirishnoma.

### Admin
Yangi bo'lim "Sovg'alar" (nav `gifts`, "Savdo" guruhida; ruxsat `PRICING_READ`/`PRICING_UPDATE`): jadval (emoji, nom, Stars, sotuv narxi, tuzatish maydoni, yoqish/o'chirish, qoldiq), "Sinxronlash", botning Stars balansi va oxirgi sinxronlash vaqti, balans past bo'lsa ogohlantirish. API: `GET /api/admin/gifts`, `POST /api/admin/gifts/sync`, `PATCH /api/admin/gifts/{id}` (`enabled`, `title`, `price_override_uzs`). Narx o'zgarishi mavjud qoida bo'yicha xavfli tasdiq bilan. "Narxlar" bo'limidagi eski sovg'alar tahriri olib tashlanadi.

### Do'kon va bot
Web App: sovg'a mahsuloti sahifasida qabul qiluvchi: "O'zimga" yoki "Boshqa odamga" (Chatdan tanlash asosiy yo'l; qo'lda `@username` faqat botni bilgan odam uchun). Bosh sahifadagi "Sovg'alar" plitkasi va ro'yxat yangi katalogdan. Botdagi do'kon menyusining sovg'alar bo'limi (`shop.py`) ham yangi katalogdan o'qiydi va yangi yetkazishdan foydalanadi (u allaqachon `users_shared` orqali ID oladi).

### Tekshirish
Soxta bot bilan birlik/integratsiya testlari (muvaffaqiyat, har xato turi, ikki marta yubormaslik, qaytarish, narx, ruxsatlar, `cost_uzs` chiqmasligi, sinxronlash). **Haqiqiy sinov (egasi):** botga eng arzon sovg'a narxicha Stars qo'yib, o'zingizga bitta sovg'a yuborish — balansdan yechilishini, xato matnlarini va ID bilan yuborishni tasdiqlaydi.

## Aniqlashtirishlar (quruvchi tekshiruvidan keyin)

- **Pul qaytarish:** mijoz buyurtma uchun hamyonidan to'laydi (`wallet`/`balance`); qaytarish ham har doim hamyonga (`wallet_service.credit_balance`, `tx_type="refund"`), bu mavjud xatti-harakat.
- **Narx qotiriladi:** buyurtma yaratilganda narx serverda hisoblanib hamyondan yechiladi (`order.total_price`); keyingi kurs o'zgarishi mavjud buyurtmaga ta'sir qilmaydi. `cost_price` har doim `calculate_stars_price(star_count)` dan (override bo'lsa ham).
- **Qattiq o'tish (cutover):** eski katalog sotuvdan olinadi. Joylashtirish paytida to'langan, lekin yetkazilmagan eski uslubdagi sovg'a buyurtmalari (`recipient_user_id` yo'q yoki `item_title` Telegram sovg'a ID'si emas) avtomatik yuborilmaydi, `manual_review` ga o'tkazilib adminga ko'rsatiladi.
- **Botning Stars balansi:** keshdagi balansdan hali yetkazilmagan sovg'a buyurtmalarining jami `star_count` i ayriladi (zaxira); baribir yetmasa, `sendGift` xatosi doimiy xato sifatida qaytarishga olib keladi. Past balans ogohlantirishi: balans eng arzon yoqilgan sovg'adan kam bo'lsa (yoki 100 Stars dan kam).
- **Cheklangan sovg'alar:** `remaining_count` soatlik sinxronlash darajasida yangi; tugab qolgan sovg'a yuborish paytida doimiy xato bo'lib, qaytariladi (qabul qilindi).
- **`@username`:** `users` jadvalida `id` (Telegram ID) va `username` bor; qidiruv katta-kichik harfga sezgir emas. Faqat botdan foydalangan odam topiladi. "O'zimga" — qabul qiluvchi ID'si har doim serverda tasdiqlangan foydalanuvchidan olinadi, mijoz yuborgan qiymatga ishonilmaydi. Odamning sovg'a qabul qilmasligi yuborishdan oldin aniqlanmaydi (to'lovdan keyin qaytarish bilan hal bo'ladi).

## Quruvchiga qoldirilgan qarorlar
Migratsiya tafsilotlari, xatolar tasnifining aniq jadvali, qaytarish funksiyasining aniq chaqirilishi, jadvalning admin ko'rinishi, emoji tanlash (`sticker.emoji`), sinxronlash oralig'ining aniq qiymati.

## Mening qarorlarim (egasi tekshirishi uchun)
- Narx = mavjud Stars narxi va ustamasi bo'yicha (admin tuzatishi mumkin).
- Premium-only sovg'alar ro'yxatga kiritilmaydi; tugagan cheklangan sovg'a yashiriladi.
- Noma'lum 400-xatolar doimiy xato hisoblanadi (qaytarish), tarmoq xatolari esa qo'lda ko'rib chiqishga o'tadi.
- Faqat odamlar; kanal/guruh, stiker rasmi, matn — keyingi qadam.
- `@username` ni faqat `users` jadvalida bor odam uchun qabul qilamiz.

## Topilma (bu hujjat doirasidan tashqari, lekin muhim)
`app/services/fragment.py:215-243` (`send_ton_transaction`) hech qanday haqiqiy TON o'tkazmasi yubormaydi: simulyatsiya rejimida yoki mnemonic bo'sh bo'lsa `sim_...` soxta tx raqami, mnemonic bo'lsa ham `tx_...` soxta raqam yasab `success: True` qaytaradi. Natijada **Stars va Premium buyurtmalari haqiqatda yetkazilmasdan "bajarildi" deb belgilanadi va mijozga "yetkazildi" xabari ketadi** (mahalliy bazadagi ikkala buyurtmada ham soxta tx raqami bor). Sovg'a yetkazish bu yo'ldan foydalanmaydi.
