# GiftHub — Loyiha Instructions (TZ) — v2

> Bu hujjat dastlabki TZ asosida yangilangan: Broadcast bo'limiga **kanaldan forward qilish** imkoniyati va Admin boshqaruviga **botga yozgan foydalanuvchilar ro'yxatidan tanlab admin qilish** oqimi aniqlashtirilib qo'shildi (o'zgargan joylar **[YANGI]** deb belgilangan).

## 1. Loyiha g'oyasi

Telegram bot + Web App (Mini App) orqali foydalanuvchilar Telegram Stars, Telegram Premium obunasi va Premium sovg'alarni sotib olishlari mumkin bo'lgan xizmat.

**Model:** Bot Fragment orqali (TON bilan) stars/premium/gift sotib oladi → foydalanuvchi botdan so'mda (Click/Payme) sotib oladi. Foydalanuvchi avval hamyoniga balans to'ldiradi, keyin shu balansdan xarid qiladi.

---

## 2. USER TOMONI (Web App)

### 2.1. Autentifikatsiya
- Telegram Web App `initData` orqali avtomatik login — SMS/kod talab qilinmaydi.
- `initDataUnsafe.user` obyektidan: `id`, `first_name`, `last_name`, `username`, `photo_url` olinadi.
- Backend `initData`ni bot tokeni bilan hash tekshiradi (soxtalashtirishning oldini olish uchun) — bu qadam **majburiy**, aks holda xavfsizlik teshigi bo'ladi.

### 2.2. Bosh sahifa
- Balans banneri + "Hamyonni to'ldirish" tugmasi
- 3 ta asosiy bo'lim: **Telegram Premium**, **Telegram Stars**, **Premium sovg'alar**
- Har bir bo'lim bosilganda ichidagi mahsulotlar (paketlar) ochiladi

### 2.3. Hamyon (Balance)
- Joriy balans
- To'ldirish usullari: Click, Payme (kartani to'g'ridan-to'g'ri kiritish emas — provayder checkout sahifasiga yo'naltirish orqali, xavfsizlik uchun)
- To'lovlar tarixi (kirim/chiqim)

### 2.4. Xarid oqimi
1. Foydalanuvchi mahsulot (masalan 90 Stars) tanlaydi
2. Tizim narxni hisoblaydi (pastda admin panel bo'limida tushuntiriladi)
3. Balansdan yechiladi → buyurtma "kutilmoqda" holatida yaratiladi
4. Backend Fragment orqali xaridni amalga oshiradi (avtomatik yoki admin tasdig'i bilan — pastga qarang)
5. Muvaffaqiyatli bo'lsa — buyurtma "bajarildi" ga o'tadi, foydalanuvchiga bildirishnoma boradi

### 2.5. Tarix
- Barcha buyurtmalar: mahsulot turi, sana, summa, holat (Kutilmoqda / Bajarildi / Bekor qilindi)
- Filtrlash va qidirish

### 2.6. Profil
- Ism, username, avatar (Telegram'dan avtomatik)
- Statistika: jami buyurtmalar soni, ro'yxatdan o'tgan sana
- **Referal bo'limi:**
  - Shaxsiy link: `t.me/bot_username?start=ref_<user_id>`
  - Taklif qilinganlar soni + ishlangan bonus summasi
  - Nusxalash tugmasi
- Qo'llab-quvvatlash, Ommaviy oferta, Yangiliklar kanali havolalari
- Til/ko'rinish sozlamalari

### 2.7. Majburiy kanal a'zoligi
- Foydalanuvchi botga birinchi kirganda (yoki botdan foydalanishdan oldin) belgilangan kanal(lar)ga a'zo bo'lishi shart.
- **[YANGI/ANIQLASHTIRISH]** Bu tekshiruv — Web App ichida doimiy ko'rinadigan banner emas, balki bitta marta ko'rinadigan **kirish ekrani (gate)**: foydalanuvchi kanal(lar)ga a'zo bo'ladi → "Tekshirish" tugmasini bosadi → backend `getChatMember` orqali tasdiqlaydi → shundan keyingina asosiy menyu (Bosh sahifa) ochiladi. A'zo bo'lmasa, xarid/funksiyalar bloklanadi va shu ekranda qoladi.

---

## 3. ADMIN PANEL

Bu loyihaning eng muhim va nozik qismi — quyidagilar aniq ishlab chiqilishi kerak:

### 3.1. Narx belgilash tizimi (eng muhim qism)

**Muammo:** Fragment'da narxlar odatda paket asosida beriladi (masalan 50 stars = X TON), lekin foydalanuvchi 90 stars xohlashi mumkin.

**Yechim — "narx bir birlik uchun" tizimi:**
- Admin bitta **bazaviy narx** kiritadi: masalan "1 dona Stars uchun tannarx (TON/so'mda)" + "1 dona Stars uchun sotish narxi (so'mda)"
- Tizim istalgan miqdor uchun avtomatik hisoblaydi: `narx = birlik_narxi × miqdor`
- Ustiga **minimal margin/foiz** qo'shish imkoniyati (masalan tannarxga +15% avtomatik qo'shiladi)
- Katta miqdorlar uchun chegirma darajalari (masalan 500+ stars uchun -5%) — ixtiyoriy, lekin foydali
- Xuddi shu mantiq **Premium** (3/6/12 oylik uchun alohida narx) va **Gifts** (har bir sovg'a uchun alohida, chunki ular soni cheklangan/individual) uchun ham qo'llaniladi
- Admin panelda: "Tannarxni yangilash" tugmasi — TON kursi o'zgarsa, barcha narxlarni qayta hisoblash imkoniyati

### 3.2. Mahsulotlarni boshqarish
- Fragment'dan qaysi xizmatlar (stars, premium muddatlari, gift turlari) botga qo'shilishini yoqish/o'chirish
- Har biriga rasm, nom, tavsif qo'shish

### 3.3. Referal tizimini boshqarish
- Bonus foizi yoki summasi (masalan xaridning 5%)
- **Shart qo'yish imkoniyati:** bonus faqat taklif qilingan foydalanuvchi minimal summa (masalan 20,000 so'm)dan xarid qilgandan keyin beriladi — bu "soxta referal" firibgarligining oldini oladi
- Bonus qanday beriladi: avtomatik hamyonga tushishi yoki admin tasdig'i bilan (tanlov)

### 3.4. Majburiy obuna **[ANIQLASHTIRILDI]**
- Uchta turdagi majburiy shart qo'llab-quvvatlanadi:
  1. **Oddiy a'zolik** — foydalanuvchi kanal/guruhga a'zo bo'lishi kerak, bot `getChatMember` orqali avtomatik tekshiradi.
  2. **So'rov orqali qo'shilish** — kanal/guruh "so'rov bilan qo'shilish" (join request) rejimida bo'lsa, bot `chat_join_request` hodisasi orqali so'rov yuborilganini biladi va shartni bajarilgan deb belgilaydi.
  3. **Tashqi havola** — Telegram bo'lmagan yoki bot admin bo'lmagan resurs (Instagram, YouTube, veb-sayt va h.k.). Bunday shart **avtomatik tekshirilmaydi** — foydalanuvchiga faqat havola ko'rsatiladi, bosilgach shart bajarilgan hisoblanadi (soft-shart). Bu qoida boshida aytib qo'yilishi kerak: bunday shartlar haqiqatda majburlanmaydi, faqat ko'rsatiladi.
- **Yangi kanal qo'shish oqimi — muhim texnik chegara:** Bot API orqali administratorning shaxsiy akkountida qaysi kanal/guruhlarga u admin ekanligi haqida ro'yxatni oldindan olib bo'lmaydi (bu ma'lumot faqat foydalanuvchi client-sessiyasida mavjud, Bot API'da yo'q). Shu sababli quyidagi oqim qo'llaniladi:
  1. Admin botni istalgan kanal/guruhga o'zi qo'lda admin qilib qo'shadi (Telegram interfeysining o'zida).
  2. Bot bu holatni **`my_chat_member`** hodisasi orqali avtomatik aniqlaydi (bot statusi "member" dan "administrator"ga o'zgarganda Telegram bu haqda botga webhook yuboradi).
  3. Aniqlangan kanal admin panelda "Yangi aniqlangan" sifatida ko'rinadi — admin turini (Oddiy a'zolik / So'rov orqali qo'shilish) tanlaydi va "Majburiy qilish" bosadi.
- Kanal qo'shish/o'chirish, har bir kanalni yoqish/o'chirish (faollik toggle'i) imkoniyati saqlanadi.

### 3.5. Reklama yuborish (Broadcast) **[YANGILANDI]**
- Barcha foydalanuvchilarga yoki segmentlarga (masalan "xarid qilmaganlar", "faol foydalanuvchilar", "referal orqali kelganlar") xabar yuborish
- **Uchta xil xabar yaratish rejimi:**
  1. **Yozish** — matn + rasm + inline tugma admin panelning o'zida yoziladi (asl variant)
  2. **[YANGI] Kanaldan forward qilish** — admin biror kanaldagi tayyor postni (username yoki post havolasini kiritib) tanlaydi, tizim o'sha postni **forward** qiladi (asl formatlash, rasm, tugmalari bilan) — qayta yozish shart emas. Bu marketing kanalida allaqachon joylashtirilgan e'lonni bir tugma bilan foydalanuvchilarga yuborish uchun.
  3. **[YANGI] PostBotdan olib kelish** — admin PostBot (yoki boshqa post-yaratuvchi bot)da tayyorlagan xabarni GiftHub admin botiga **forward** qiladi; tizim forward qilingan xabarni (matn, rasm, tugmalari bilan) tanib oladi va uni tayyor broadcast kontenti sifatida saqlaydi — qayta qo'lda yig'ish shart emas.
  - Backend tomonda: Telegram Bot API'ning `forwardMessage` / `copyMessage` metodidan foydalaniladi (`copyMessage` afzalroq — chunki "Forwarded from" belgisisiz yuboradi va botning o'z nomidan ko'rinadi). PostBot rejimi uchun ham xuddi shu mantiq — admin panelga forward qilingan xabar `message_id` orqali saqlanadi va keyin `copyMessage` bilan barcha foydalanuvchilarga ko'chiriladi.
- Yuborish tezligini cheklash kerak (Telegram rate limit — soniyasiga ~30 xabar), aks holda bot bloklanishi mumkin — bu ikkala rejim uchun ham amal qiladi
- Test yuborish (faqat adminning o'ziga) imkoniyati tavsiya etiladi

### 3.6. Statistika
- Kunlik/haftalik/oylik: yangi foydalanuvchilar, jami savdo, eng ko'p sotilgan mahsulotlar
- Foyda hisoboti (sotish narxi − tannarx)
- Referal orqali kelgan foydalanuvchilar statistikasi

### 3.7. Adminlarni boshqarish (professional usul) **[ANIQLASHTIRILDI]**
- ID qo'lda kiritish o'rniga: admin panelda **"Admin qo'shish"** tugmasi bosiladi.
- Tugma bosilganda modal/oyna ochiladi va ikkita usul taklif qilinadi:
  1. **Forward orqali** — admin o'zi adminlik bermoqchi bo'lgan odamdan kelgan istalgan xabarni shu admin botga forward qiladi. Bot forward ma'lumotidan (`forward_origin`) o'sha odamning user ID/username'ini oladi va uni nomzod sifatida ko'rsatadi. **Eslatma:** agar foydalanuvchi Telegram sozlamalarida "forward manbasini yashirish"ni yoqqan bo'lsa, bu usul ishlamaydi — shunda username orqali qidirish kerak bo'ladi.
  2. **Username orqali** — admin `@username` kiritadi; tizim bu foydalanuvchini faqat botning o'z bazasidan (ya'ni u avval botga yozgan/ro'yxatdan o'tgan bo'lsa) topa oladi, chunki bot hali unga xabar yubormagan odamni user ID orqali topa olmaydi (Telegram cheklovi).
  - **Muhim texnik chegara:** bot hech qanday holatda administratorning shaxsiy Telegram akkauntidagi (ilovadagi) umumiy xabarlashish/kontaktlar ro'yxatini o'qiy olmaydi — bu Bot API imkoniyatlaridan tashqarida va buni amalga oshirish shaxsiy akkauntga server orqali kirishni talab qilardi, bu esa jiddiy xavfsizlik va maxfiylik xatari hisoblanadi. Shu sababli yuqoridagi ikki usul (forward va username) qo'llaniladi.
- Nomzod tanlangandan so'ng **rol tanlanadi** (Super Admin / Narx admin / Support admin / Marketing admin) → **"Admin qilish"** tugmasi bosiladi → foydalanuvchi shu zahoti tanlangan rol bilan admin bo'ladi.
- **Rollar tizimi tavsiya etiladi** (bittasi hammasini emas):
  - *Super Admin* — hamma narsaga ruxsat, adminlarni boshqaradi
  - *Narx admin* — faqat narxlarni o'zgartira oladi
  - *Support admin* — faqat buyurtmalar/foydalanuvchilar bilan ishlaydi, narxga tegmaydi
  - *Marketing admin* — faqat broadcast va referal sozlamalari
- Har bir admin harakati **log** qilinishi kerak (kim, qachon, nima o'zgartirdi) — bu keyinchalik muammo chiqsa, kim javobgarligini bilish uchun juda muhim. Bu jurnal admin panelda alohida "Harakatlar jurnali" sifatida ko'rinadi.

### 3.8. To'lov usullarini boshqarish **[YANGI]**
- Admin panelda har bir to'lov usulini alohida yoqish/o'chirish mumkin.
- **Rasmiy usullar (asosiy, tavsiya etiladi):** Click va Payme — litsenziyalangan to'lov provayderlari, standart usul sifatida yoqilgan bo'ladi.
- **AutoPayCard (norasmiy, faqat backup uchun):** shaxsiy Uzcard karta + shu kartaga bog'liq Gmail (App Password orqali) yordamida ishlaydigan uchinchi tomon xizmati. Mexanizmi: tizim har bir to'lov uchun noyob summa (`asosiy_summa + tasodifiy(1-99)`) yaratadi, foydalanuvchi aynan shu summani ko'rsatilgan shaxsiy kartaga o'tkazadi, xizmat Gmail'dagi bank xabarnomasini o'qib to'lovni aniqlaydi va webhook yuboradi.
  - **Xavf-xatarlar (admin panelda ogohlantirish sifatida ko'rsatiladi):**
    - Gmail App Password butun pochta hisobiga to'liq kirish huquqini beradi — faqat shu maqsad uchun alohida ochilgan Gmail hisobidan foydalanish shart.
    - Shaxsiy kartani muntazam tijorat oqimi uchun ishlatish ko'plab banklarning foydalanish shartlariga zid bo'lishi mumkin — karta bloklanish xavfi mavjud.
    - Xizmat litsenziyalanmagan, kichik uchinchi tomon loyihasi — uzoq muddatli barqarorlik va nizo holatida huquqiy himoya kafolatlanmaydi.
  - Shu sabablarga ko'ra tizimda **standart holatda o'chirilgan** va faqat admin ongli ravishda yoqqandan keyin ishlaydi; asosiy oqim sifatida emas, balki qo'shimcha/vaqtinchalik usul sifatida taqdim etiladi.
  - Sozlamalar: API kalit (@Autopaycardbot orqali olinadi), karta oxirgi 4 raqami, ulangan Gmail, webhook URL.

---

## 4. TEXNIK ARXITEKTURA (tavsiya)

- **Bot:** Python (aiogram yoki python-telegram-bot)
- **Web App:** React yoki oddiy HTML/CSS/JS, Telegram Web App SDK bilan
- **Backend API:** FastAPI yoki Django REST
- **Baza:** PostgreSQL
- **Fragment integratsiyasi:** rasmiy API yo'q — unofficial kutubxona yoki browser automation (Playwright) orqali; bu **beqaror** bo'lishi mumkinligini hisobga oling, fallback sifatida "admin qo'lda tasdiqlaydi" rejimi ham qo'shish tavsiya etiladi (ayniqsa boshida)
- **To'lov:** Click va Payme rasmiy API integratsiyasi
- **Broadcast:** Telegram Bot API — `copyMessage` (forward rejimi uchun) va oddiy `sendMessage`/`sendPhoto` (yozish rejimi uchun), navbat (queue) orqali ~30 xabar/soniya tezlikda yuborish
- **Hosting:** VPS (masalan Beget, Timeweb, yoki DigitalOcean) + webhook orqali bot

---

## 5. XAVFSIZLIK BO'YICHA ESLATMALAR

- `initData` hashini har doim serverda tekshiring, hech qachon frontendga ishonmang
- Admin panel alohida autentifikatsiya (faqat ro'yxatdagi Telegram ID'lar kira oladi) bilan himoyalangan bo'lishi kerak
- Fragment/TON wallet kalitlarini hech qachon frontend yoki repo'da saqlamang — faqat serverda, environment variable sifatida
- Har bir moliyaviy tranzaksiya (balans o'zgarishi) bazada **audit log** bilan yozilishi kerak — kim, qachon, qancha, nima uchun
- Admin qo'shish oqimida ham audit log yozilishi shart: kim, qaysi foydalanuvchini, qanday rol bilan admin qilgani

---

## 6. Qo'shimcha g'oyalar (ko'rib chiqish uchun)

- **Promo-kodlar / chegirma kodlari** — marketing uchun (masalan "GIFTHUB10" — 10% chegirma)
- **VIP/loyalty daraja tizimi** — ko'p xarid qilgan foydalanuvchilarga avtomatik chegirma
- **Kam balans haqida eslatma** — foydalanuvchiga push xabar
- **Fragment xaridi muvaffaqiyatsiz bo'lsa avtomatik qaytarish (refund)** logikasi — bu juda muhim, aks holda pul yo'qolib qolishi mumkin
- **Qo'llab-quvvatlash uchun ichki chat/ticket tizimi** — alohida admin bilan yozishish, tashqi guruhga chiqmasdan
- **Ko'p tillilik** (o'zbek/rus/ingliz) — agar auditoriya kengaysa
- **Narxlar tarixi grafigi** (admin uchun) — TON kursi o'zgarishini kuzatib borish
- **Statistikani Excel/CSV formatda eksport qilish**

---

Bu hujjatni Claude Code'ga yoki boshqa dasturchiga topshirsangiz, ular shu asosda loyihani boshlashlari mumkin.
