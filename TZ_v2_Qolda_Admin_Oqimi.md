# TZ v2 — Qo'lda Admin Oqimi (Manual Admin Flow)

> **Holat:** loyiha (draft). Muhokama asosida yozildi, ba'zi punktlar hali
> aniqlashtirilishi kerak — 14-bo'limga qarang.
> **Oldingi hujjat:** `TZ_Data_Relay_System.md` (v1, avtomatik bot-pool oqimi).

---

## 1. Maqsad va o'zgarish sababi

### 1.1 Nima uchun o'zgartiryapmiz

v1 tizimi mijozdan **nomer + kupon** olib, ularni avtomatik ravishda
**tekshiruv botlari pooliga** (5–10 bot) uzatardi. Amaliyotda ma'lum bo'ldiki:

> Tekshiruv **botga emas, tirik odamning lichkasiga** yuborilishi kerak —
> kimningdir akkaunti orqali o'tmasa bu tizim ishlamas ekan.

Shu sababli tizimning roli tubdan o'zgaradi:

| | v1 | **v2** |
|---|---|---|
| Tizim roli | Botni almashtiruvchi (mijoz sezmaydi) | **Adminning yordamchisi** (admin ishlaydi, tizim osonlashtiradi) |
| Tekshiruv manzili | 5–10 ta tekshiruv bot | **1 ta tekshiruvchi lichka** (tirik odam) |
| Kupon | Majburiy, asosiy | **Kerak emas — faqat nomer** |
| Admin akkaunti | 1 ta | **5+ ta**, har biri o'z sessiyasi bilan |
| Kuzatuv | Faqat kiruvchi xabarlar | Kiruvchi **+ chiquvchi** (admin o'zi yozgani) |
| Nazorat | Yo'q | Guruh arxivi + reaksiya + statistika |

### 1.2 Tizim adminning qaysi ikki ishini osonlashtiradi

1. **Rasmlarni guruhga tashlash** — admin mijozga rasm tashlaganda, tizim
   o'sha rasmlarni avtomatik nazorat guruhiga forward qiladi, tagiga vaqt,
   admin ismi va mijoz nomerini yozadi. (Hozir admin buni qo'lda qiladi.)
2. **1.5 soatdan keyin nomerni tekshirish** — tizim o'zi tekshiruvchi
   lichkaga so'rov yuboradi, javobni tanib oladi, mijozga aytadi va guruhdagi
   postga 👍/👎 qo'yadi. Admin `/check` bilan istalgan vaqtda tezlashtira oladi.

---

## 2. Ishtirokchilar

| Ishtirokchi | Tavsif |
|---|---|
| **Mijoz** | Admin lichkasiga nomerini yozadi |
| **Admin (operator)** | 5+ ta. O'z shaxsiy Telegram akkaunti bilan mijozlar bilan yozishadi. Har birining akkauntida bizning Telethon sessiyamiz ishlaydi |
| **Tekshiruvchi lichka** | 1 ta akkaunt. Nomerni oladi, kupon bazasidan tekshiradi, "bor/yo'q" deb javob beradi |
| **Nazorat guruhi** | 1 ta umumiy Telegram guruhi. Rasmlar + izohlar arxivi. Natija reaksiya bilan belgilanadi |
| **Adminbot** | aiogram bot. Adminlarga bildirishnoma, tugmalar, statistika, sozlamalar |
| **Superadmin** | `.env` dagi ID + bot orqali qo'shilganlar. Hamma statistika va sozlamalarga huquqli |

---

## 3. Umumiy oqim

**Nomer faqat MATN ko'rinishida taniladi** (v1 dagi `extract_phone`
mexanizmi — tabiiy suhbat ichidan ajratib olish). Telegram "kontakt
ulashish", ovozli xabar yoki rasm ichidagi nomer **ishlanmaydi** — bunday
holatda admin mijozdan nomerni yozib yuborishini so'raydi.

```
T0        Mijoz nomer yozadi
          └→ Case ochiladi, assigned_admin_id = o'sha admin
          └→ scheduled_jobs: due_at = T0 + 90daq  (kind = REMIND_CHECK)

T0+n      Admin mijozga 1–3 rasm tashlaydi
          └→ rasmlar bitta partiya qilib guruhga forward + caption
          └→ mijoz lichkasida rasm tagiga shablon matn
          └→ taymer QAYTA boshlanadi: due_at = rasm_vaqti + 90daq
          └→ status: SCREENSHOTS_SENT

T+90daq   ┌─ rasm tashlangan bo'lsa  → CHECK_QUEUED
          └─ rasm tashlanmagan bo'lsa → adminga eslatma, tekshiruv YO'Q

          yoki istalgan vaqtda: admin reply + /check → taymer bekor, darhol navbatga

navbat    Global tomchilagich (drip) → so'rov o'sha ADMINNING O'Z AKKAUNTIDAN
          tekshiruvchi lichkaga ketadi → CHECK_SENT

javob     Tekshiruvchi yozadi → shablon orqali tanib olinadi
          ├→ PASSED       → mijozga AVTOMATIK yoziladi, guruhga 👍
          ├→ FAILED       → adminbotda tugma, admin tasdiqlagach yoziladi, guruhga 👎
          └→ NEEDS_ADMIN  → mijozga hech narsa, guruhga ⚠️, admin qo'lda hal qiladi
```

---

## 4. Modul 1 — Ko'p akkauntli Telethon

### 4.1 Talab

5 tadan ko'p admin akkaunti bir vaqtda kuzatiladi. Har akkaunt uchun alohida
Telethon sessiyasi.

### 4.2 Arxitektura

- **Bitta jarayon, N ta klient** (asyncio). Har `TelegramClient` bitta
  `admin_id` bilan bog'lanadi — shuning uchun har bir hodisada "qaysi admin"
  savoli avtomatik javob topadi. Statistika aynan shundan chiqadi.
- Sessiya fayllari: `sessions/admin_<id>.session`.
- Login bir marta qo'lda: telefon → SMS kod → (kerak bo'lsa) 2FA parol.
  Buning uchun alohida CLI skript: `scripts/add_admin_session.py`.

### 4.2a Yangi admin qo'shish

Yangi adminning akkauntiga login (telefon → SMS kod → 2FA parol) **superadmin
o'zi** serverda `scripts/add_admin_session.py` orqali bajaradi. Adminbot
orqali kod kiritish oqimi **qilinmaydi** (Telegram qoidalariga nozik va
xavfsizlik jihatdan shubhali). Sessiya yaratilgach `admin_sessions` jadvaliga
yoziladi va klient avtomatik ishga tushadi (jarayonni qayta ishga tushirish
bilan yoki issiq-qo'shish bilan — B-1 da hal qilinadi).

### 4.2b Admin nofaol bo'lsa (ishdan ketdi / uzoq ta'til)

Superadmin adminbotda adminni **"nofaol"** deb belgilaydi. Shunda:

- O'sha adminning barcha **ochiq case'lari muzlatiladi** — taymerlar,
  eslatmalar, avtomatik tekshiruvlar to'xtaydi.
- Superadminga muzlatilgan case'lar **ro'yxati** boradi (mijoz, nomer,
  holat, qancha turgani) — kimga qo'lda bog'lanishni o'zi hal qiladi.
- Adminning Telethon klienti to'xtatiladi (sessiya faylı o'chirilmaydi).
- Admin qaytsa — "faol" deb belgilanadi, muzlatilgan case'lar davom etadi
  (taymerlar qayta hisoblanadi).

### 4.3 Sessiya salomatligi

Admin telefonida "Terminate all sessions" bossa yoki parolni o'zgartirsa,
sessiya o'ladi va o'sha adminning mijozlari **jimgina yo'qoladi**. Bu real xavf.

- Har klient uchun holat kuzatiladi: `CONNECTED / DISCONNECTED / AUTH_LOST`.
- Sessiya uzilsa → superadminga **darhol** alert:
  `🔴 Aziz (+99890...) sessiyasi uzildi — qayta login kerak`
- Adminbotda `Sessiyalar` bo'limi: har akkaunt holati, oxirgi faollik vaqti.

### 4.4 Cheklovlar (flood-wait)

Har akkaunt uchun **alohida** throttling hisoblagichi. Telegram cheklovi
kelganda (`FloodWaitError`) o'sha akkaunt belgilangan vaqtga to'xtatiladi,
navbatdagi ishlar kutadi, superadminga xabar boradi.

### 4.5 Xavfsizlik eslatmasi

Shaxsiy akkauntdan avtomatik forward / reaksiya / xabar yuborish Telegram
tomonidan cheklanishi mumkin. Shuning uchun:
- Har amal orasida tabiiy pauza (tasodifiy 1–3 soniya).
- Tizim **hech qachon** o'zi birinchi bo'lib begona odamga yozmaydi —
  faqat mijoz yozgan suhbatlarda javob beradi.

---

## 5. Modul 2 — Rasm ushlash va guruhga tashlash

### 5.1 Ushlash

Admin mijoz lichkasiga rasm tashlaganda tizim uni **chiquvchi** xabar sifatida
ko'radi (`events.NewMessage(outgoing=True)`).

**⚠️ Faol case sharti:** rasm faqat o'sha mijozda **ochiq case** bo'lsa
(nomer qabul qilingan, tekshiruv hali yakunlanmagan) partiya sifatida
olinadi. Case yo'q yoki allaqachon yopilgan bo'lsa — rasm **oddiy suhbat**
hisoblanadi: guruhga tushmaydi, bazaga yozilmaydi. Shu orqali adminning
tizimga aloqasiz rasmlari (meme, hujjat, boshqa mavzu) guruhni iflos qilmaydi.

**Partiyaga birlashtirish:** odatda 2 ta, ba'zan 1 yoki 3 ta rasm bo'ladi.
- Agar albom (`grouped_id`) bo'lsa → bitta partiya.
- Aks holda **N soniyalik oyna** (standart 15 soniya, sozlanadi): shu vaqt
  ichida bitta mijozga ketgan hamma rasm bitta partiya hisoblanadi.

### 5.2 Guruhga tashlash

Partiya to'liq yig'ilgach umumiy nazorat guruhiga forward qilinadi (qayta
yuklamasdan — `file_id` orqali, sifat va tezlik uchun).

**Caption formati** (dastlabki loyiha, tasdiqlanishi kerak):

```
📸 #C1247
👤 @username (Dilnoza)
📱 +998 90 123 45 67
🧑‍💼 Admin: Aziz Karimov
🕐 14:32 · 11.08.2026
⏳ Tekshiruv: 16:02
```

- Vaqt **Toshkent** vaqtida (UTC+5), `utcnow()` emas.
- `#C1247` — case'ning qisqa kodi, guruhda qidirish uchun.
- Mijozga havola: `tg://user?id=<tg_user_id>`.

### 5.3 Mijoz lichkasidagi matn

Rasmlar yuborilgach mijozga avtomatik shablon matn tushadi (adminbotdan
tahrirlanadi), masalan:

> Kuponingiz tekshirish jarayonida. Iltimos 1.5 soatdan keyin eslating.

### 5.4 Dublikat nomer ogohlantirishi ⚠️

**Mezon — Telegram akkaunti emas, NOMER.**

- Bir xil nomer boshqa adminga ham yozilsa — **muammo yo'q**, hech qanday
  ogohlantirish yo'q, jim o'tadi.
- Lekin o'sha nomer uchun **ikkinchi marta rasm partiyasi** guruhga tushsa —
  demak ikki admin bitta mijoz ustida ishlayapti (yoki bitta admin ikki
  marta). Bu holatda:
  - Guruhga tashlash **to'xtatilmaydi**.
  - Caption'ga qo'shiladi: `⚠️ Bu nomer uchun avval ham rasm tashlangan — #C1189 (Admin: Bekzod, 12:05)`
  - **Superadminga alert** boradi.
  - `screenshot_batches.is_duplicate = True` belgilanadi — statistikada
    ikki marta hisoblanmasligi uchun.

### 5.5 Chekka holatlar

| Holat | Xatti-harakat |
|---|---|
| Admin rasm tashladi, lekin mijoz hali nomer yubormagan | Guruhga tashlanmaydi. Adminbotda: `⚠️ Nomer topilmadi — rasm guruhga tushmadi`. Mijoz keyin nomer yozsa, oxirgi 30 daqiqadagi rasmlar o'sha case'ga bog'lanadi |
| Admin 3 tadan ko'p rasm tashladi | Hammasi bitta partiyada ketadi, caption'da soni yoziladi |
| Admin rasmni o'chirsa | Guruhdagi post qoladi (arxiv). Adminbotda belgi qo'yiladi |
| Guruh sozlanmagan | Rasmlar ushlanadi va bazaga yoziladi, lekin hech qayerga yuborilmaydi. Superadminga: `⚠️ Nazorat guruhi sozlanmagan` |

---

## 6. Modul 3 — Tekshiruv dvigateli

### 6.1 Ishga tushish yo'llari

**(a) Avtomatik — 1.5 soatlik taymer**

**Taymer sanovi rasm tashlangan vaqtdan boshlanadi.** Mijozga aytilgan
"1.5 soat" u rasmni ko'rgan vaqtdan hisoblanishi mantiqan to'g'ri.

```
14:00  nomer keldi          → kuzatuv boshlanadi (rasmsizlik eslatmasi uchun)
14:20  admin rasm tashladi  → due_at = 15:50
15:50  tekshiruv ishga tushadi
```

- Rasm tashlanmasa — **tekshiruv umuman rejalashtirilmaydi**, o'rniga
  rasmsizlik kuzatuvi ishlaydi (quyida).
- Admin rasmni ikkinchi marta tashlasa — taymer oxirgi rasm vaqtidan
  qayta hisoblanadi.

**(a2) Rasmsizlik eslatmasi — mijoz holatiga qarab 2 xil**

Eslatma matni mijoz **kupon raqamini yuborgan-yubormaganiga** qarab
o'zgaradi, chunki bu ikki butunlay boshqa vaziyat:

| Mijoz holati | Ma'nosi | Adminga xabar |
|---|---|---|
| **Kupon bor** | Mijoz allaqachon ovoz bergan | `⚠️ Dilnoza (+998 90 123 45 67) kupon raqamini yubordi — siz rasm tashlashni unutdingiz` |
| **Kupon yo'q** | Mijoz hali ovoz bermagan | `⚠️ Dilnoza (+998 90 123 45 67) nomer yubordi — uning ovozini ham olib qo'ying` |

- Birinchi eslatma nomer kelganidan `NO_SCREENSHOT_FIRST_MINUTES` (standart
  30 daqiqa) keyin.
- Keyin `NO_SCREENSHOT_REMINDERS` marta takrorlanadi (standart 3 ta).
- Admin rasm tashlashi bilan eslatmalar to'xtaydi va tekshiruv taymeri
  boshlanadi.

**3 ta eslatmadan keyin ham rasm yo'q bo'lsa → superadminga o'tadi:**

```
🔴 Aziz 3 ta eslatmaga javob bermadi
👤 Dilnoza (@username) · +998 90 123 45 67 · #C1247
🕐 Nomer 14:00 da kelgan · 4s 30daq o'tdi
🎫 Kupon: yo'q (mijoz hali ovoz bermagan)
```

- Case **yopilmaydi**, ochiq qoladi — admin keyin rasm tashlasa oqim davom etadi.
- Statistikada `tashlab ketilgan` sifatida alohida hisoblanadi.
- Superadmin qarorini o'zi qabul qiladi (adminni turtish, o'zi yozish va h.k.).

**(b) Qo'lda — `/check`**

Admin mijoz yozgan **nomerli xabarga reply qilib** `/check` yozadi.

- `/check` xabari **darhol o'chiriladi** — mijoz komandani ko'rmasligi kerak.
- Rejalashtirilgan avtomatik ish **bekor qilinadi** (ikki marta tekshirilmasin).
- Reply topilmasa yoki reply'da nomer bo'lmasa → `/check +998901234567`
  ko'rinishi ham qabul qilinadi.
- Nomer umuman topilmasa → adminbotda xato xabari.

**(a3) Ish vaqti — 24/7**

Ovoz olingan case'lar uchun (nomer + kupon qabul qilingan va rasm tashlangan)
avtomatik tekshiruv **kecha-kunduz ishlaydi** — taymer kechasi tushsa ham
so'rov tekshiruvchiga yuboriladi. Tekshiruvchi uxlayotgan bo'lsa, so'rov
navbatda javob kutadi (§6.5 — hech narsa yo'qolmaydi); javob kelgach natija
odatdagidek tarqatiladi. Alohida "ish soatlari" cheklovi **yo'q**.

**(a4) Qayta tekshiruv — faqat admin qo'li bilan**

Avtomatik qayta sikl **yo'q**. Natija chiqqandan keyin:

| Vaziyat | Xatti-harakat |
|---|---|
| Natija **O'TMADI** chiqdi | Admin xohlasa **`/check` bilan qayta tekshiradi** — yangi `check_request` ochiladi, statistikada `is_recheck=True` deb belgilanadi |
| Mijoz **o'sha nomerni qayta tashladi** (avval o'tmagan) | Admin nomerni **qaytadan kiritib ko'rishi mumkin** — yangi sikl admin tashabbusi bilan boshlanadi, tizim o'zi avtomatik boshlamaydi |
| Natija **O'TDI** bo'lgan, nomer qayta keldi | Mijozga "allaqachon tasdiqlangan" shablon javobi, tekshiruvchi bezovta qilinmaydi |

**"O'TDI" natijasi abadiy** — muddati yo'q, mavsum tushunchasi kiritilmaydi.
Yangi kampaniya boshlanib eski natijalar xalaqit beradigan bo'lsa, baza
qo'lda tozalanadi (arxivlash skripti bilan — B-6 da oddiy `scripts/`
buyrug'i sifatida qo'shib qo'yiladi).

### 6.2 Global tomchilagich (drip)

Tekshiruvchi — tirik odam. 1.5 soatlik taymerlar birdaniga ishga tushsa,
unga o'nlab xabar yog'iladi.

- Barcha adminlar bo'ylab **umumiy** navbat.
- Chiqish tezligi sozlanadi (standart: har **20 soniyada 1 ta**).
- Navbat **bazada** turadi (`check_requests` + `scheduled_jobs`), xotirada
  emas — restart'da yo'qolmaydi.

### 6.3 So'rov yuborish

So'rov **o'sha adminning o'z akkauntidan** tekshiruvchi lichkaga boradi.

> Bu muhim afzallik: har adminning tekshiruvchi bilan **alohida dialogi** bor,
> shuning uchun javob qaysi so'rovga tegishli ekani chalkashmaydi. Har chat
> uchun mustaqil FIFO — bir vaqtda o'sha chatda faqat 1 ta ochiq so'rov.

**Tayyorgarlik talabi:** tekshiruvchi har bir admin akkauntini kontaktga
qo'shishi (yoki hech bo'lmaganda ulardan xabar qabul qilishi) kerak — aks
holda Telegram maxfiylik sozlamasi xabarni to'sib qo'yadi.

### 6.4 Javobni tanish (shablon dvigateli)

Tekshiruvchining javobi **matn shablonlari** orqali tanib olinadi. Shablonlar
kodda emas — **adminbot orqali matn ko'rinishida kiritiladi** va istalgan
vaqtda o'zgartiriladi (tizimni qayta ishga tushirmasdan).

Mexanizm v1 dagi `bot_patterns` naqshiga asoslanadi, lekin bot emas, **tirik
odamning erkin matni** bilan ishlagani uchun ancha mustahkam bo'lishi kerak.

#### 6.4.1 Kategoriyalar

| Kategoriya | Ma'nosi | Shablon soni |
|---|---|---|
| `CHECK_PASSED` | Ovoz o'tgan / bazada bor | **ro'yxat** (bir nechta) |
| `CHECK_FAILED` | Ovoz o'tmagan / topilmadi | **ro'yxat** |
| `CHECK_ERROR` | Xato, "qayta yuboring", "noto'g'ri nomer" | **ro'yxat** |

Har kategoriyaga **cheklanmagan soncha** variant kiritiladi — odam har safar
bir xil yozmaydi ("o'tdi", "bor", "✅", "ha o'tgan", "прошел").

#### 6.4.2 Normallashtirish

Taqqoslashdan oldin matn tozalanadi:
- kichik harfga o'tkaziladi;
- ortiqcha bo'shliqlar bittaga siqiladi;
- apostrof variantlari birxillashtiriladi (`'` `'` `ʻ` `` ` `` → `'`);
- emojilar alohida token sifatida saqlanadi (`✅` ham shablon bo'la oladi);
- lotin/kirill va o'zbekcha/ruscha variantlar alohida shablon sifatida
  kiritiladi (avtomatik translit qilinmaydi — xato manbai bo'ladi).

#### 6.4.3 ⚠️ Tekshirish tartibi — eng muhim qoida

Salbiy javoblar ko'pincha ijobiy so'zni **o'z ichiga oladi**:

> `CHECK_PASSED` = `bor` bo'lsa, *"bazada **bor** emas"* xato tanib olinadi.

Shuning uchun tartib qat'iy:

```
1. CHECK_FAILED  tekshiriladi   ← avval SALBIY
2. CHECK_ERROR   tekshiriladi
3. CHECK_PASSED  tekshiriladi   ← oxirida IJOBIY
```

Qo'shimcha himoya (PASSED va FAILED birga mos kelganda — qamrab olish qoidasi):
- Ijobiy moslik salbiy iboraning **ichida** bo'lsa ("bazada **bor** emas" —
  "bor" mosligi "~bor emas" ichida) → bu haqiqiy salbiy javob, natija
  **FAILED**.
- Ijobiy moslik salbiydan **alohida joyda** tursa ("o'tdi yoki o'tmadi") →
  haqiqiy qarama-qarshilik → `NEEDS_ADMIN`. Tizim **hech qachon taxmin
  qilmaydi**.
- Shablon standart holatda **butun so'z** bo'yicha qidiriladi (`bor` so'zi
  `borligi` ichida topilmaydi).

#### 6.4.4 Shablon formati

| Yozilishi | Ma'nosi |
|---|---|
| `o'tdi` | butun so'z sifatida qidiriladi (standart) |
| `~bazada bor` | ichida qidiriladi (substring) |
| `=✅` | matn aynan shunga teng bo'lsa |
| `re:o'?t(di\|gan)` | regex (faqat tajribali foydalanuvchi uchun) |

#### 6.4.5 Qaysi xabar hisobga olinadi va so'rovga bog'lash

Faqat **o'sha adminning** tekshiruvchi bilan chatidagi, **bizning
so'rovimizdan keyin** kelgan xabarlar ko'riladi.

Tekshiruvchi javobni uch xil ko'rinishda yozishi mumkin (foydalanuvchi
tasdiqlagan real odatlar). Javobni so'rovga bog'lash ustuvorligi:

| # | Ko'rinish | Bog'lash usuli |
|---|---|---|
| 1 | Nomerli xabarga **reply** qilib "bor" | `reply_to` orqali **aniq** o'sha so'rovga — eng ishonchli |
| 2 | "...1234 bor" — **oxirgi 4 raqam** bilan | Ochiq so'rovlar ichidan oxirgi 4 raqami mos kelganiga |
| 3 | Shunchaki "bor" | O'sha chatdagi **eng eski ochiq so'rovga** (FIFO) |

- 2-usulda mos keluvchi so'rov topilmasa yoki **ikkitadan ortiq** mos kelsa
  → `NEEDS_ADMIN` (taxmin qilinmaydi).
- 3-usul faqat o'sha chatda **bitta** ochiq so'rov bo'lsa xavfsiz; bir nechta
  bo'lsa → `NEEDS_ADMIN`. (Drip navbati "har chatda bir vaqtda 1 ta so'rov"
  qoidasini saqlagani uchun bu holat kam uchraydi.)
- Birinchi xabar hech qaysi shablonga mos kelmasa (masalan *"bir daqiqa"*) —
  **kutiladi**, keyingi xabar tekshiriladi.
- `CHECKER_STALL_MINUTES` ichida hech narsa tanilmasa → `NEEDS_ADMIN`.

#### 6.4.6 Adminbotdagi vositalar

| Vosita | Vazifasi |
|---|---|
| `Tanish shablonlari` menyusi | Har kategoriya bo'yicha qo'shish / o'chirish / ro'yxat |
| **`/testcheck <matn>`** | Sinov: berilgan matn qanday tanib olinishini ko'rsatadi (`✅ PASSED — "o'tdi" shabloniga mos`). Jonli ishga tushirishdan oldin haqiqiy javoblarni tashlab tekshirib ko'rish uchun |
| **Tanilmagan javoblar jurnali** | Oxirgi tanilmagan javoblar ro'yxati, har biriga tugma: `[O'TDI] [O'TMADI] [XATO]`. Bir marta bosilsa — o'sha matn shablonga **avtomatik qo'shiladi**. Shablonlar haqiqiy trafikdan o'sib boradi |
| **Soya rejimi** (`SHADOW_MODE`) | Tizim tanib oladi, bazaga yozadi, guruhga reaksiya qo'yadi — lekin **mijozga hech narsa yozmaydi**. Birinchi kunlar uchun xavfsizlik tormozi |

#### 6.4.7 Ishga tushish himoyasi

- Har uch kategoriyada **kamida bitta** shablon bo'lmaguncha tekshiruv
  dvigateli ishga tushmaydi (v1 dagi `missing_patterns` naqshi saqlanadi).
- Hech qaysi shablonga mos kelmagan javob → `NEEDS_ADMIN`, mijozga
  **hech narsa yozilmaydi**, guruhda ⚠️.

> 💡 **Tavsiya:** birinchi 1–2 kun **soya rejimida** ishlatilsin. Shu vaqt
> ichida tanilmagan javoblar jurnalidan shablonlar to'ldiriladi, keyin jonli
> rejimga o'tiladi. Shunda mijozga xato javob ketish xavfi deyarli nolga tushadi.

### 6.5 Javob kelmasa

- So'rov **navbatda qoladi** — yo'qolmaydi, javob kelguncha kutadi.
- 30 daqiqadan keyin (sozlanadi) superadminga alert:
  `⏳ 7 ta so'rov javobsiz. Eng eskisi: +99890... (Aziz), 1s 20daq`
- Mijozga **hech narsa yozilmaydi**.
- Status: `CHECK_STALLED` (guruhda ⏳ reaksiya).

**Kech javob (case allaqachon hal bo'lgandan keyin kelsa):**

Tekshiruvchi javobi case yopilgandan keyin (masalan admin qo'lda hal qilib
bo'lgach) kelsa — javob **avtomatik qo'llanadi**:

1. Natija bazada **to'g'irlanadi** (`late_corrected=True` belgisi bilan —
   statistikada alohida ko'rinadi).
2. Guruhdagi reaksiya yangilanadi (👎 → 👍 yoki aksincha).
3. O'sha adminga adminbotda xabar boradi:
   `⚠️ Kech javob keldi: bu mijozning ovozi O'TGAN ekan (siz O'TMADI deb
   yopgansiz). Mijozdan uzr so'rab, to'g'ri natijani yozing.`
4. **Mijozga tizim yozmaydi** — admin o'zi uzr so'rab yozadi (bu insoniy
   muloqot, shablon bilan emas).
5. Kech javob avvalgi natija bilan **bir xil** bo'lsa — hech narsa
   o'zgarmaydi, faqat bazaga yoziladi (tasdiq sifatida).

Case hali **ochiq** bo'lsa (admin hech narsa qilmagan) — kech javob oddiy
javobdek ishlanadi, hech qanday maxsus ishlov kerak emas.

**Tekshiruvchi uzoq muddat ishlamay qolsa** (ta'til, kasallik) — oldindan
zaxira akkaunt tutilmaydi. Superadmin adminbotdagi `CHECKER_ACCOUNT`
sozlamasini yangi akkauntga o'zgartiradi — yangi so'rovlar darhol yangi
manzilga keta boshlaydi. Ochiq (javobsiz) so'rovlar ham yangi tekshiruvchiga
qayta yuboriladi. Shablonlar umumiy, qayta kiritish shart emas.

### 6.6 Takroriy tekshiruv (kesh)

Bitta nomer 10 daqiqa ichida qayta tekshirilmoqchi bo'lsa (masalan ikki admin
`/check` qilsa), tekshiruvchiga qayta so'rov **yuborilmaydi** — oxirgi natija
qaytariladi. Muddati sozlanadi.

---

## 7. Modul 4 — Natija tarqatish

### 7.1 Aralash rejim

| Natija | Mijozga | Guruhga | Adminbotga |
|---|---|---|---|
| ✅ **PASSED** | **avtomatik yoziladi** (shablon) | 👍 | ma'lumot uchun xabar |
| ❌ **FAILED** | admin tugma bosgach | 👎 | **[Mijozga yuborish] [Yo'q]** |
| ⚠️ **NEEDS_ADMIN** | yozilmaydi | ⚠️ | qo'lda hal qilish tugmalari |
| ⏳ **STALLED** | yozilmaydi | ⏳ | superadminga alert |

Sabab: "o'tdi" — xavfsiz xabar, avtomatik ketaveradi. "O'tmadi" — nozik
xabar, admin ko'zi bilan bir marta ko'rib tasdiqlagani ma'qul.

### 7.2 Mijozga yuboriladigan matn

Adminning **o'z akkaunti** orqali, shablondan (adminbotdan tahrirlanadi).
Alohida shablonlar: `RESULT_PASSED`, `RESULT_FAILED`.

### 7.3 Guruhdagi reaksiya

- Tizim **avtomatik** qo'yadi: 👍 o'tdi · 👎 o'tmadi · ⚠️ noaniq · ⏳ javobsiz.
- Odam qo'lda o'zgartirsa — tizim buni **o'qib bazaga yozadi**
  (`outcome_source = MANUAL`, `reacted_by` = kim qo'ygani). Bu qo'lda
  tuzatish (override) sifatida statistikada alohida ko'rinadi.
- Guruh **oddiy guruh** (forum/mavzular emas), reaksiyalar ochiq bo'ladi.
  **Har ehtimolga qarshi:** reaksiya qo'yish muvaffaqiyatsiz bo'lsa (guruh
  sozlamasida reaksiyalar yopilgan, emoji cheklangan, huquq yetmaydi) —
  natija baribir **bazaga yoziladi** va superadminga darhol alert:
  `⚠️ Guruhda reaksiya qo'yib bo'lmadi — reaksiyalar yopilgan bo'lishi mumkin`.

### 7.4 Adminga xabar

Har holatda o'sha admin adminbotda qisqa xabar oladi:

```
✅ +998 90 123 45 67 — ovozi O'TDI
👤 Dilnoza (@username) · #C1247
🕐 16:04 · avtomatik tekshiruv
```

---

## 8. Modul 5 — Statistika

### 8.1 Qayerda ko'rinadi

1. **Adminbotda** — tugmali menyu: `Bugun / Hafta / Oy / Admin bo'yicha`.
2. **Nazorat guruhiga kunlik hisobot** — har kuni **21:00** da avtomatik xulosa.
3. **Superadmin lichkasiga** — o'sha vaqtda batafsilroq nusxa (guruhdagi
   xulosaga qo'shimcha: tashlab ketilganlar, javobsiz so'rovlar, dublikatlar,
   sessiya muammolari).

> Web panel (`panel_service/`) bu bosqichda kengaytirilmaydi.

### 8.2 Ko'rsatkichlar (admin kesimida)

| Ko'rsatkich | Manba |
|---|---|
| Qabul qilingan nomer | `cases` |
| Rasm partiyasi / jami rasm soni | `screenshot_batches` |
| Dublikat rasm (⚠️) | `screenshot_batches.is_duplicate` |
| Qo'lda `/check` vs avtomatik | `check_requests.trigger` |
| O'tdi / O'tmadi / Noaniq / Javobsiz | `check_requests.result` |
| Konversiya % | `passed / (passed + failed)` |
| Rasmsiz qolgan (eslatma ketgan) | `scheduled_jobs` |
| O'rtacha: nomer → rasm vaqti | `batch.sent_at − case.created_at` |
| O'rtacha: so'rov → javob vaqti | `replied_at − sent_at` |

### 8.3 Kunlik guruh hisoboti (namuna)

```
📊 11.08.2026 yakuni

Jami: 47 nomer · 44 rasm · 41 tekshiruv
✅ 33 o'tdi   ❌ 8 o'tmadi   ⚠️ 0 noaniq   ⏳ 3 javobsiz

Aziz      20 nomer · 18 tekshirildi · 15 ✅ / 3 ❌  (83%)
Bekzod    15 nomer · 14 tekshirildi · 12 ✅ / 2 ❌  (86%)
Dilshod   12 nomer · 9 tekshirildi  ·  6 ✅ / 3 ❌  (67%)  ⚠️ 3 ta rasmsiz
```

### 8.4 Ruxsat

- **Superadmin** (`.env` dagi ID lar) — hammasini ko'radi.
- Bot orqali qo'shilgan **kuzatuvchi adminlar** — hammasini ko'radi.
- **Oddiy admin** — faqat o'z statistikasini ko'radi.

Mavjud rol tizimi (`AdminRole`: OWNER / ROP / DASTURCHI / ADMIN / KUZATUVCHI)
qayta ishlatiladi, `UNRESTRICTED_ROLES` mantiqi kengaytiriladi.

### 8.5 Kelajakda (bu bosqichda emas)

Tekshiruvchi lichka kesimida statistika: har admin undan nechta so'rov qildi,
nechtasi tasdiqlandi, o'rtacha javob vaqti qancha.

---

## 9. Ma'lumotlar modeli

### 9.1 Yangi jadvallar

```
admin_sessions
  id · admin_id → admins.id · session_name · phone
  status (CONNECTED/DISCONNECTED/AUTH_LOST) · last_seen_at · last_error

screenshot_batches
  id · case_id → cases.id · admin_id → admins.id
  phone · image_count · file_ids (JSON)
  group_chat_id · group_message_id
  is_duplicate (bool) · duplicate_of_batch_id
  sent_at
  outcome (PENDING/PASSED/FAILED/UNKNOWN/STALLED)
  outcome_source (AUTO/MANUAL) · reacted_by · reacted_at

check_requests
  id · case_id → cases.id · phone
  requested_by_admin_id → admins.id
  trigger (MANUAL/AUTO) · queued_at · sent_at · replied_at
  result (PASSED/FAILED/UNRECOGNIZED/NO_REPLY) · raw_reply
  customer_notified_at · notified_by (AUTO/ADMIN)

scheduled_jobs
  id · kind (CHECK_DUE / REMIND_NO_SCREENSHOT / STALLED_ALERT / DAILY_REPORT)
  case_id · due_at · payload (JSON) · done_at · attempts
```

### 9.2 Mavjud jadvallarga qo'shimcha

```
admins    + can_view_all_stats (bool)
cases     + short_code       (masalan "C1247")
          + coupon           (mijoz yuborgan kupon raqami, NULL bo'lishi mumkin)
          + coupon_at        (qachon yuborilgani)
```

**Kupon nima uchun saqlanadi** (tekshiruvga ishlatilmasa ham):
1. **Mijoz holati signali** — kupon bor = ovoz bergan, yo'q = hali bermagan.
   Rasmsizlik eslatmasi aynan shunga qarab ikki xil bo'ladi (§6.1 a2).
2. **Dalil** — nizoli holatda mijoz nima yuborganini ko'rsatadi.
3. **Kelajak** — kerak bo'lsa tayyor turadi, keyin qo'shish qimmat.

### 9.3 O'zgartirilgan `CaseStatus`

**Qoladi:** `NUMBER_RECEIVED`, `SUSPICIOUS_HOLD`, `NEEDS_ADMIN`

**Yangi:** `SCREENSHOTS_SENT`, `CHECK_QUEUED`, `CHECK_SENT`, `PASSED`,
`FAILED`, `CHECK_STALLED`

**Olib tashlanadi (ishlatilmaydi):** `SENT_TO_BOT`, `AWAITING_COUPON`,
`COUPON_SENT_TO_BOT`, `CONFIRMED`, `REJECTED`, `EXPIRED`, `TIMEOUT`,
`CUSTOMER_TIMEOUT`, `EXPIRED_SESSION`, `DUPLICATE_ACTIVE`, `ALREADY_CONFIRMED`

> v1 TZ dagi "bu ro'yxatdan tashqari status qo'shilmaydi" cheklovi **bekor
> qilinadi** — v2 yangi holat mashinasiga ega.

### 9.4 Muhim: taymerlar bazada

v1 da mijoz taymeri **xotirada** edi (`CaseManager._customer_timers`,
asyncio task). 5 daqiqa uchun bu maqbul edi. **1.5 soat uchun emas** —
restart bo'lsa hamma kutayotgan tekshiruv yo'qoladi.

Shuning uchun barcha vaqt-tayanchli ishlar `scheduled_jobs` jadvalida saqlanadi,
poller har 30 soniyada muddati kelganlarni oladi.

---

## 10. Sozlamalar (adminbot orqali)

| Kalit | Tavsif | Standart |
|---|---|---|
| `GROUP_CHAT_ID` | Nazorat guruhi | — |
| `CHECK_DELAY_MINUTES` | Tekshiruvgacha kutish | 90 |
| `IMAGE_BATCH_WINDOW_SECONDS` | Rasmlarni bitta partiya deb hisoblash oynasi | 15 |
| `DRIP_INTERVAL_SECONDS` | Tekshiruvchiga so'rov chiqish tezligi | 20 |
| `CHECKER_ACCOUNT` | Tekshiruvchi lichka (username / ID) | — |
| `CHECKER_STALL_MINUTES` | Javobsizlik alert vaqti | 30 |
| `CHECK_CACHE_MINUTES` | Takroriy tekshiruv keshi | 10 |
| `NO_SCREENSHOT_FIRST_MINUTES` | Birinchi rasmsizlik eslatmasigacha | 30 |
| `NO_SCREENSHOT_REMINDERS` | Rasmsizlik eslatmalari soni | 3 |
| `DAILY_REPORT_TIME` | Kunlik hisobot vaqti (guruh + superadmin) | 21:00 |
| **`SHADOW_MODE`** | Soya rejimi — mijozga hech narsa yozilmaydi (§6.4.6) | **yoqilgan** |
| Shablonlar | `SCREENSHOT_CAPTION`, `RESULT_PASSED`, `RESULT_FAILED` | — |
| Tanish shablonlari | `CHECK_PASSED`, `CHECK_FAILED`, `CHECK_ERROR` (ro'yxat) | — |

Sozlash huquqi: **superadmin** va superadmin belgilagan adminlar.

---

## 11. Xato va chekka holatlar

| Holat | Xatti-harakat |
|---|---|
| Telethon sessiyasi o'ldi | Superadminga darhol alert, o'sha admin ishlari to'xtaydi |
| `FloodWaitError` | O'sha akkaunt kutadi, navbat saqlanadi, alert |
| Tekshiruvchi javob bermadi | Navbatda qoladi + alert (6.5) |
| Javob tanilmadi | `NEEDS_ADMIN`, mijozga hech narsa, guruhda ⚠️ |
| Guruh sozlanmagan | Rasmlar bazaga yoziladi, alert |
| Nomer topilmasdan rasm | Guruhga tushmaydi, adminbotda xato, 30 daqiqa "kutish" |
| Bir nomer ikkinchi marta rasm oldi | Guruhga tushadi + ⚠️ belgi + superadmin alert (5.4) |
| Restart | `scheduled_jobs` va navbat bazada — hech narsa yo'qolmaydi |
| Guruhdan post o'chirilgan | Reaksiya qo'yib bo'lmaydi — bazaga yozilaveradi, log |

---

## 12. Eski koddan nima bo'ladi

| Komponent | Taqdiri |
|---|---|
| `VerificationBot` protokoli | ✅ Qayta ishlatiladi — `CheckerAccountAdapter` yoziladi |
| `bot_patterns` mexanizmi | ✅ Qayta ishlatiladi — tekshiruvchi javobini tanish uchun |
| Shubhali holat mantiqi | ✅ Saqlanadi (bir nomer turli akkauntdan) |
| `notifier`, `templates`, `audit_log`, `settings_store` | ✅ Saqlanadi, kengaytiriladi |
| `backup`, `logging_setup` | ✅ O'zgarishsiz |
| `openbudget` moduli | ✅ O'zgarishsiz |
| **`bot_pool.py`** (5–10 bot, LRU) | ⚪️ **Kod qoladi, ulanmaydi** |
| **Kupon mantiqi** (`coupon.py`, `CouponAttempt`) | ⚪️ **Kod qoladi, ulanmaydi** |
| Kupon/EXPIRED testlari | ⚪️ Skip qilinadi yoki alohida papkaga ko'chiriladi |
| `panel_service` | ⚪️ Tegilmaydi (bu bosqichda kengaytirilmaydi) |

> **⚪️ "Kod qoladi, ulanmaydi"** = fayllar o'chirilmaydi, lekin hech qayerdan
> chaqirilmaydi. Keyinchalik kerak bo'lsa qarab olish mumkin.

---

## 13. Joylashtirish (deployment)

### 13.1 Talablar

Tizim **to'xtovsiz (24/7)** ishlashi kerak — 5+ Telethon ulanishi doimo ochiq
turadi. Shuning uchun **VPS/VDS shart**, virtual (shared) xosting **yaramaydi**:

| Talab | Sabab |
|---|---|
| **Root huquqi** | Xizmatlarni o'rnatish, `systemd`, port boshqaruvi |
| **≥ 2 GB RAM** | 5+ Telethon klient + adminbot + panel + SQLite |
| **≥ 20 GB disk** | Kutubxonalar (~500 MB) + baza + loglar + backuplar + sessiyalar |
| **≥ 2 CPU yadro** | Parallel sessiyalar va fon vazifalari |
| **24/7 jarayon** | Shared xosting uzoq ishlaydigan jarayonni o'ldiradi |

> ❌ **Tekshirilgan va rad etilgan:** aHOST Germaniya "Birinchi" tarifi
> (33 800 so'm/oy) — bu **shared xosting**: 500 MB disk, root yo'q, Docker yo'q,
> uzoq ishlaydigan jarayon kafolatlanmagan. Bu loyiha uchun yaramaydi.

### 13.2 🔴 Server qaysi davlatda bo'lishi — xavfsizlik masalasi

Bu oddiy veb-loyiha emas: serverda **5+ ta shaxsiy Telegram akkaunti** ishlaydi.

Telegram akkauntga kirilgan **geografiyani kuzatadi**. Admin Toshkentda
bo'lib, akkaunti chet eldagi data-markazdan ulansa — Telegram buni shubhali
deb hisoblab **sessiyani uzishi** yoki qo'shimcha tasdiqlash so'rashi mumkin.
5+ akkaunt bilan bu jiddiy va takrorlanuvchi xavf.

**Qaror:** server **O'zbekiston (TAS-IX)** hududida bo'lgani ma'qul —
geografiya adminlarning haqiqiy joylashuviga mos keladi.

### 13.3 Usuli — Dockersiz (systemd)

Docker **ishlatilmaydi** (birinchi bosqichda). Sabab: birinchi haftalarda
ko'p qo'lda ish bo'ladi — 5+ akkauntga login, shablonlarni sozlash, soya
rejimida kuzatish, xato tuzatish. Bular Dockersiz ancha oson kechadi.

Uch xizmat `systemd` orqali ishlaydi:

| Xizmat | Buyruq |
|---|---|
| `teleton.service` | `python -m teleton_service.relay` |
| `adminbot.service` | `python -m adminbot_service.bot` |
| `panel.service` | `uvicorn panel_service.app:app` (ixtiyoriy) |

Har biri `Restart=always` bilan — server qayta yonsa yoki jarayon yiqilsa
avtomatik ko'tariladi.

> `Dockerfile` va `docker-compose.yml` **o'chirilmaydi** — keyinchalik
> Docker'ga o'tish kerak bo'lsa, tayyor turadi.

### 13.4 🔴 Sessiya fayllari xavfsizligi

Serverda 5+ adminning `.session` fayllari turadi. **Bu fayl kimning qo'liga
tushsa — o'sha adminning butun Telegram akkauntiga to'liq kirish oladi**
(barcha shaxsiy yozishmalari, kontaktlari bilan). Shuning uchun:

- Serverga kirish huquqi: **faqat superadmin va superadmin belgilagan
  odamlar**. SSH parol bilan emas, **kalit (key) bilan** himoyalanadi,
  parol orqali kirish o'chiriladi.
- `sessions/` papkasi huquqlari qattiq cheklanadi (`chmod 700`, faqat
  xizmat foydalanuvchisi o'qiy oladi).
- Sessiya fayllari **backupga qo'shilmaydi** — kunlik backup faqat SQLite
  bazani oladi. (Sessiya yo'qolsa qayta login qilinadi — bu fayl nusxasining
  tarqalib ketishidan ko'ra arzon xavf.)
- Adminlarga ochiq aytiladi: tizim ularning akkauntida ishlaydi va
  texnik jihatdan yozishmalarini ko'ra oladi — rozilik olinadi.

---

## 14. Bosqichlar

| Bosqich | Mazmuni |
|---|---|
| **B-1 · Poydevor** | Ko'p Telethon sessiyasi, sessiya salomatligi, chiquvchi xabar kuzatuvi, yangi ma'lumotlar modeli + migratsiya, eski oqimni uzish |
| **B-2 · Rasm oqimi** | Partiyaga yig'ish, guruhga forward + caption, mijozga shablon matn, dublikat nomer ogohlantirishi |
| **B-3 · Tekshiruv dvigateli** | `scheduled_jobs` + poller, drip navbat, `/check` (+ o'chirish), `CheckerAccountAdapter`, shablon dvigateli + `/testcheck` + tanilmagan javoblar jurnali + soya rejimi |
| **B-4 · Natija** | Aralash rejim (avto/tasdiqlash), mijozga yuborish, guruhga reaksiya, adminbot tugmalari |
| **B-5 · Statistika** | Adminbot menyusi, ruxsatlar, kunlik guruh hisoboti |
| **B-6 · Mustahkamlash** | Chekka holatlar, alertlar, flood himoyasi, testlar, `systemd` joylashtirish |

---

## 15. Ochiq savollar

### ✅ Hal qilinganlar

| Savol | Qaror |
|---|---|
| Tekshiruvchi javob namunalari | Adminbot orqali matn sifatida kiritiladi (§6.4) |
| Taymer anchori | **Rasm tashlangan vaqtdan** |
| Rasmsizlik eslatmasi | Kupon bor/yo'qligiga qarab **2 xil matn** (§6.1 a2) |
| Kupon raqami | Bazaga saqlanadi, holat signali sifatida ishlatiladi (§9.2) |
| Statistika ruxsati | Oddiy admin **faqat o'zinikini** ko'radi (§8.4) |
| 3 eslatmadan keyin | **Superadminga o'tadi**, case ochiq qoladi (§6.1 a2) |
| Kunlik hisobot | Guruhga **21:00** + superadmin lichkasiga (§8.1) |
| Guruh caption | §5.2 dagi format tasdiqlandi |
| Reaksiya emojilari | 👍 o'tdi · 👎 o'tmadi · ⚠️ noaniq · ⏳ javobsiz |
| Server | **VDS** (shared xosting yaramaydi), **Dockersiz** — systemd (§13) |
| Ish soatlari | Yo'q — ovoz olingan case'lar **24/7** tekshiriladi (§6.1 a3) |
| Nomer shakli | **Faqat matn** — kontakt/ovoz/rasm ishlanmaydi (§3) |
| Qayta tekshiruv | Avtomatik sikl yo'q — faqat admin `/check` bilan (§6.1 a4) |
| Begona rasm | Faqat **ochiq case** bo'lsa ushlanadi (§5.1) |
| Tekshiruvchi zaxirasi | Yo'q — kerak bo'lsa `CHECKER_ACCOUNT` almashtiriladi (§6.5) |
| Admin nofaol bo'lsa | Case'lar muzlatiladi + superadminga ro'yxat (§4.2b) |
| Mavsum | Yo'q — "O'TDI" abadiy, kerak bo'lsa qo'lda arxivlash skripti (§6.1 a4) |
| Server kirish huquqi | Faqat superadmin + u belgilaganlar; sessiya himoyasi (§13.4) |
| Guruh turi | Oddiy guruh, reaksiyalar ochiq; yopilib qolsa alert (§7.3) |
| Yangi admin login | Superadmin o'zi serverda `add_admin_session.py` bilan (§4.2a) |
| Javobni bog'lash | reply > oxirgi 4 raqam > FIFO; noaniqlikda NEEDS_ADMIN (§6.4.5) |
| Kech javob | **Avtomatik to'g'irlanadi** + adminga xabar; mijozga admin o'zi uzr so'rab yozadi (§6.5) |

### ⏳ Ochiq qolganlar

1. ⏸ **Tekshiruvchiga so'rov formati** — nomer qanday yuborilsin?
   (`+998901234567` / `901234567` / `Tekshiring: +998 90 123 45 67`)
   *Keyinchalik ko'rib chiqiladi.*
2. **Aniq VDS tarifi tanlanmagan.** Minimum talab: 2 GB RAM, 20 GB disk,
   2 yadro, root. aHOST'da bunga `VDS Cloud 50` (200 000 so'm/oy) eng past
   chegara, `VDS Cloud 100` (320 000 so'm/oy) qulayroq. Narxlarni buyurtma
   oldidan qayta tekshirish kerak.
3. **Mijozga yuboriladigan matnlar** — rasm tagidagi, "o'tdi", "o'tmadi".
   Aniq matnlarini bering yoki standartni tasdiqlang. *(Bularning hammasi
   adminbotdan tahrirlanadi, shuning uchun taxminiy matn bilan boshlab,
   keyin to'g'irlash mumkin.)*
