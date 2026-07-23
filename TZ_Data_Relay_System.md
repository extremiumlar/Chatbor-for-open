# TEXNIK TOPSHIRIQ (TZ) — v2.1
## Kupon Tekshirish va Nazorat Avtomatlashtirish Tizimi

> **Versiya:** 2.1 (foydalanuvchi javoblari asosida qayta ishlangan)
> **Sana:** 2026-07-21
> **Rejim:** Shaxsiy / test -> keyin ishlab chiqarish
> **Status:** MUHOKAMA BOSQICHI — hali tasdiqlanmagan nuqtalar 16-bo'limda

---

## 0. ATAMALAR (juda muhim — chalkashmaslik uchun)

| Atama | Ma'nosi |
|---|---|
| **Teleton** | Biz quryotgan asosiy tizim. Bu **bot EMAS**. Telethon orqali admin(lar)ning shaxsiy Telegram akkauntiga ulanib, lichkani avtomatlashtiradi. |
| **Tekshiruv botlari** | Boshqa dasturchi yasagan, **o'zgartirib bo'lmaydigan** 5–10 ta "qora quti" bot. Nomerni oladi, kupon so'raydi, kuponni tekshirib natija beradi. Teleton ularni galma-gal ishlatadi. |
| **Adminbot** | Biz yasaydigan yagona bot. Adminlar uchun: sozlash, nazorat, bildirishnoma, boshqaruv. |
| **Admin (operator)** | O'z Telegram akkauntini Teletonga ulagan xodim. Mijozlar bilan lichkada gaplashadi. |
| **Owner / Rop / Dasturchi** | Yuqori rollar (kelajakda batafsil bo'linadi — Q25). |
| **Mijoz (foydalanuvchi)** | Adminning lichkasiga yozadigan oddiy odam. Nomer va kupon yuboradi. |
| **Case (murojaat)** | Bitta nomerning to'liq jarayoni (nomer -> kupon -> tasdiq). Kupon muddati o'tsa yangilanadi, lekin case o'sha nomernik. |

---

## 1. TIZIMNING ASOSIY MOHIYATI

Adminlar mijozlar bilan **oddiy lichka suhbati** olib boradi. Suhbat orasida
mijoz **telefon nomerini** tashlaydi. Teleton buni avtomatik ilg'ab oladi va
tekshiruv botiga uzatadi. Bot kupon so'raydi -> Teleton mijozdan (admin
tasdiqlagan matn bilan) kupon so'raydi -> mijoz 6 xonali kupon yuboradi ->
Teleton uni botga uzatadi -> bot natija beradi (tasdiq / rad / muddati o'tgan) ->
Teleton natijaga qarab mijozga javob beradi va adminbotga xabar yuboradi.

**Mijoz butun jarayonda faqat admin bilan gaplashayotgandek his qiladi** —
u bot borligini bilmaydi.

---

## 2. TO'LIQ JARAYON OQIMI (asosiy stsenariy)

```
1. Mijoz lichkaga oddiy gaplashadi... gap orasida NOMER tashlaydi.
       |
2. Teleton nomerni ilg'aydi (regex) -> BO'SH tekshiruv botini tanlaydi (pool)
   -> o'sha botni shu case-ga BIRIKTIRADI (lock) -> nomerni botga yuboradi.
       |
3. Bot "kupon raqamini yuboring" deb so'raydi (Teleton buni tanib oladi).
       |
4. Teleton mijozga ADMIN TASDIQLAGAN "kupon so'rash matni"ni yuboradi.
       |
5. Mijoz biroz vaqt o'tib 6 xonali KUPON tashlaydi.
       |
6. Teleton kuponni AYNAN O'SHA botga (case-ga biriktirilgan) yuboradi.
       |
7. Bot javob beradi:
       +- MUVAFFAQIYATLI  -> status CONFIRMED
       +- MUDDATI O'TGAN  -> status EXPIRED (qayta oqim, 2.1 ga qara)
       +- RAD ETILDI      -> status REJECTED
       |
8. Teleton natijaga mos ADMIN TASDIQLAGAN matnni mijozga yuboradi.
   (CONFIRMED bo'lsa mijozga "sizning ishingiz tasdiqlandi" xabari ham boradi.)
       |
9. Adminbot orqali natija haqida adminga xabar. Bot band-lik holatidan bo'shaydi.
       |
10. Case bazaga to'liq yozildi (kim, qaysi nomer, qaysi kupon, qaysi admin, vaqt).
```

### 2.1. Muddati o'tgan kupon (qayta oqim) — Q57/Q58/Q59 TASDIQLANGAN (yakuniy)

```
Bot "muddati o'tgan" deydi -> status EXPIRED
   -> Teleton mijozga tasdiqlangan matn yuboradi:
        "Kuponingiz muddati o'tdi. Qaytadan urinib ko'rish uchun
         nomeringizni qaytadan yuboring."
   -> BOT DARHOL BO'SHAYDI (case bot-dan uzatiladi) — o'sha bot shu daqiqada
      boshqa mijozning case-ini xizmat qilishi mumkin (pool ga qaytadi).
   -> Case holati EXPIRED bo'lib, "mijoz nomer yuborishini kutmoqda" holatida
      turadi (bot band emas, faqat case navbatda emas — passiv kutish).
       │
   -> Mijoz (istalgan vaqtda, tez yoki kech) NOMERNI QAYTA yuboradi
   -> Bu YANGI URINISH sifatida qabul qilinadi: xuddi yangi nomer kelgandek,
      Teleton bo'sh botni pool dan tanlaydi (3.1 qoidasi bo'yicha —
      bu OLDINGI botning aynan o'zi ham, boshqa bot ham bo'lishi mumkin).
   -> O'sha bot case-ga qayta biriktiriladi, nomer botga kiritiladi,
      bot yana kupon so'raydi -> Teleton mijozdan yangi kupon so'raydi.
       │
   -> Mijoz kupon yuboradi:
        - Agar bu kupon OLDINGI (allaqachon muddati o'tgan) kupon bilan
          BIR XIL bo'lsa -> Teleton BOTGA YUBORMAYDI, "boshqa kupon
          yuborishingiz kerak, bu eskisi bilan bir xil" deb qaytaradi (Q58).
        - Aks holda botga yuboriladi, natija kutiladi.
   -> Case-ning "urinishlar soni" (attempt count) +1 oshadi.
```

**Urinishlar limiti (Q59 — TASDIQLANGAN):** Bir case uchun EXPIRED-qayta-urinish
sikli **maksimal 5 marta** takrorlanishi mumkin. 5-urinishdan keyin ham
muddati o'tsa, case holati `NEEDS_ADMIN`ga o'tadi — admin qo'lda ko'rib chiqadi.

> Case_id o'zgarmaydi (bir xil murojaat davom etadi), lekin **bot_id har safar
> o'zgarishi mumkin** — chunki har EXPIRED dan keyin bot pool ga qaytadi va
> keyingi urinishda istalgan bo'sh bot tayinlanishi mumkin (3.1 LRU qoidasi).

### 2.2. Mijoz kuponni yubormasa — 5 daqiqalik timeout (Q48 — TASDIQLANGAN)

```
Nomer botga yuborildi + mijozdan kupon so'raldi
   -> 5 daqiqa (sozlanadigan) sanoq boshlanadi
   -> Mijoz 5 daqiqa ichida kupon yubormasa:
        - SEANS TO'XTATILADI
        - bot band-likdan BO'SHAYDI (boshqa case-larga ishlatiladi)
        - case statusi -> CUSTOMER_TIMEOUT
   -> Agar mijoz 5 daqiqadan KEYIN kupon (yoki xabar) yuborsa:
        - Teleton javob beradi: "Kuponingiz muddati o'tdi. Qaytadan urinib
          ko'rish uchun nomeringizni qaytadan yuboring." (tasdiqlangan matn)
        - Mijoz nomerni qayta yuborsa -> jarayon boshidan boshlanadi (yangi bot olinadi)
```
> 5 daqiqa — adminbot orqali sozlanadigan qiymat.
> Bu qoida botlar behuda band bo'lib qolmasligini kafolatlaydi.

### 2.3. Mijoz oldingi case tugamasdan yangi nomer tashlasa (Q49 — TASDIQLANGAN)

```
Mijozning FAOL case-i bor (masalan AWAITING_COUPON yoki SENT_TO_BOT holatida)
   -> Mijoz BOSHQA (yoki o'sha) nomerni yana yuboradi
   -> Teleton BOTGA YUBORMAYDI, avval mijozdan aniqlashtiradi:
        "Sizning oldingi so'rovingiz hali yakunlanmagan. Avvalgi jarayonni
         davom ettiramizmi yoki yangi nomer bilan boshlaymizmi?"
   -> Bir vaqtda ADMINGA DARHOL xabar boradi ("mijoz N ikkinchi nomer
      yubordi, joriy case hali ochiq") — kuzatib turish uchun
   -> Mijoz javobiga (yoki admin qaroriga) qarab: eski case davom etadi
      YOKI eski case bekor qilinib yangisi boshlanadi
```
> Avtomatik hech narsa hal qilinmaydi — bu holat har doim admin nazoratida
> qoladi, chunki ikki nomer chalkashib ketishi mijoz uchun ham xavfli.

### 2.4. Tasdiqlangan nomer qayta kelsa (Q50 — TASDIQLANGAN)

```
Nomer bazada CONFIRMED holatda bor
   -> Mijoz o'sha nomerni (yoki case-ni) YANA yuborsa
   -> Teleton BOTGA UMUMAN YUBORMAYDI
   -> Avtomatik javob: "Bu nomer allaqachon tasdiqlangan." (tasdiqlangan matn)
   -> Adminbotga oddiy log (ixtiyoriy alert, muhim emas)
```

---

## 3. ENG MUHIM TEXNIK KASHFIYOT — BOTLAR POOL (NAVBAT) TIZIMI

**Bu qismni siz to'g'ridan aytmadingiz, lekin bu butun tizimning yuragi.**

Tekshiruv boti **holatli (stateful)**: u avval nomerni oladi, keyin kupon
kutadi. Bot bilan chat — bitta chiziqli suhbat. Shuning uchun:

> Bitta botga bir vaqtda IKKITA nomer yuborib bo'lmaydi — bot qaysi kupon
> qaysi nomernik ekanini bilmay qoladi va chalkashadi.

Demak botlar (5–10 ta) faqat "yukni bo'lish" uchun emas — ular **parallel
kanallar (lane)**. Har bot bir vaqtda faqat bitta case-ni yuritadi.

### 3.1. Bot pool qoidalari
- Har bir tekshiruv boti = bitta **slot** (band / bo'sh).
- Mijoz nomer tashlaganda Teleton **bo'sh** botni tanlaydi va case-ga biriktiradi.
- Bot case tugaguncha (CONFIRMED / REJECTED / TIMEOUT / **EXPIRED** / bekor) **band** turadi.
  `EXPIRED` bo'lganda ham bot **darhol bo'shaydi** — mijozning qayta nomer
  yuborishini kutish, botni band qilib turishni talab qilmaydi (2.1-bo'lim).
- Boshqa mijozlar boshqa bo'sh botlarni oladi -> parallel ishlash.
- **Hamma bot band bo'lsa** -> case navbatga (queue) tushadi + adminga alert (Q45 — TASDIQLANGAN).
- Bot tanlashda "eng uzoq ishlatilmagani" (round-robin / LRU) — yukni teng bo'lish.
- Rotatsiya **case darajasida**, xabar darajasida emas (nomer va kupon
  DOIM bitta botga boradi).

### 3.2. Bot bilan korrelyatsiya (Q13 hal bo'ldi)
Bot qora quti bo'lsa ham muammo yo'q: har bot bir vaqtda bitta case yuritgani
uchun, botdan kelgan har qanday javob **aniq o'sha case-nik**. Reply yoki
marker shart emas. (Bu — serial-per-bot modelining bonusi.)

### 3.3. Botlarni qo'shish/boshqarish (Q7)
Adminbot orqali:
- Yangi tekshiruv boti qo'shish (@username / bot bilan suhbat ochish).
- Botni yoqish / o'chirish / vaqtincha to'xtatish.
- Bot holatini ko'rish (band/bo'sh, nechta case yuritdi, xatolar).

### 3.4. Kupon validligini kim tekshiradi (Q8 — TASDIQLANGAN)
Teleton kuponni **oldindan tekshirmaydi** — faqat formatini (6 xonali raqam)
ko'radi. Kuponning haqiqiy to'g'ri/noto'g'ri/muddati o'tganligini **faqat
tekshiruv bot** hal qiladi (Teleton bazasida kuponlar ro'yxati saqlanmaydi).

### 3.5. EXPIRED holatida bot bo'shaydi (Q57 — HAL BO'LDI)
EXPIRED da bot darhol bo'shaydi (pool ga qaytadi). Mijoz keyinroq nomerni
qayta yuborganda, yangi urinish sifatida pool dan istalgan bo'sh bot qayta
tanlanadi — bir xil bot bo'lishi shart emas. To'liq tafsilot: 2.1-bo'lim.

---

## 4. MIJOZDAN NOMERNI ILG'ASH (Q1, Q10)

- Teleton mijoz xabarlarini kuzatadi, **nomer regex**iga mos kelsa jarayon boshlanadi.
- Formatlar (O'zbekiston): `997894561`, `+998997894561`, probel/chiziqcha bilan
  (`+998 99 789 45 61`, `99-789-45-61`) — hammasi normalizatsiya qilinadi.
- **Mijozdan nomer SO'RALMAYDI** — u tabiiy suhbatda o'zi tashlaydi.
- Kupon SO'RALADI (bot so'ragandan keyin, tasdiqlangan matn bilan).

### 4.1. Nomer aniqlash qoidasi (Q46 — TASDIQLANGAN)
Tasodifiy raqamlar (narx, sana, vaqt) nomer deb noto'g'ri qabul qilinmasligi
uchun **qat'iy O'zbekiston formati** talab qilinadi:
- Uzunlik: 9 xona (milliy, masalan `901234567`) yoki 12 xona (`+998` bilan xalqaro).
- **Operator kodi tekshiriladi**: `90, 91, 93, 94, 95, 97, 98, 99, 33, 88, 20` va
  h.k. haqiqiy O'zbekiston operator prefikslari ro'yxatiga mos kelishi shart.
- Probel/chiziqcha normalizatsiyadan keyin tekshiriladi.
- Operator kodlari ro'yxati adminbot orqali sozlanadi (yangi operator qo'shilsa
  kodni o'zgartirish shart bo'lmasin).

---

## 5. RASM / XATO KIRITISH (Q4, Q10, Q11)

### 5.1. Kupon o'rniga rasm yuborsa
- Teleton avtomatik javob: **"Rasm ko'rinishida emas, kod ko'rinishida
  yuboring"** (matnni adminbot orqali sozlash mumkin).
- Shu bilan birga **adminbotga WARNING** ketadi:
  - mijoz lichkasidagi ismi, telegram niki, telegram ID, nomeri (agar bor bo'lsa)
  - **inline tugma:** "Lichkaga o'tish" (admin bir bosishda o'sha suhbatga kiradi)

### 5.2. Bir nomer — turli akkauntlardan (Q11) — SHUBHALI
- Agar bitta nomer **turli telegram akkauntlaridan** kelsa -> xavfli deb belgilanadi.
- Adminbotga darhol WARNING (kim, qaysi akkauntlar, nomer).
- Case **to'xtaydi**, admin **"xavfsiz"** deb belgilamaguncha keyingi bosqichga o'tmaydi.

---

## 6. STATUS LIFECYCLE (Q26 + takomillashtirilgan)

Siz aytgan holatlar: *nomer kiritildi, kupon tasdiqlanishi kutilyapti, kupon
tasdiqlandi, mijoz uji tasdiqlandi*. Men to'liqroq qildim:

| Status | Ma'nosi |
|---|---|
| `NUMBER_RECEIVED` | Nomer ilg'andi, botga yuborishga tayyor |
| `SENT_TO_BOT` | Nomer botga yuborildi, bot "kupon?" so'rashini kutilmoqda |
| `AWAITING_COUPON` | Botdan/mijozdan kupon kutilmoqda (mijozga so'rov yuborildi) |
| `COUPON_SENT_TO_BOT` | Kupon botga yuborildi, natija kutilmoqda |
| `CONFIRMED` | Kupon tasdiqlandi (mijoz uji tasdiqlandi) |
| `REJECTED` | Kupon rad etildi |
| `EXPIRED` | Kupon muddati o'tgan -> qayta oqim kutilmoqda |
| `SUSPICIOUS_HOLD` | Shubhali (bir nomer ko'p akkaunt) — admin tasdig'i kutilmoqda |
| `NEEDS_ADMIN` | Noaniq holat — admin aralashuvi kerak |
| `TIMEOUT` | Bot javob bermadi (3 urinishdan keyin) |
| `CUSTOMER_TIMEOUT` | Mijoz 5 daqiqada kupon yubormadi -> seans to'xtatildi, bot bo'shatildi (2.2) |
| `EXPIRED_SESSION` | Mijoz jarayonni butunlay tashlab ketdi (TTL) |
| `DUPLICATE_ACTIVE` | Mijoz faol case borligida yana nomer yubordi — admin aralashuvi kutilmoqda (2.3) |
| `ALREADY_CONFIRMED` | Nomer avval tasdiqlangan, botga yuborilmadi (2.4) |

> Bitta nomer uchun bir vaqtda **bitta faol case** bo'ladi. Tasdiqlangach,
> nomer "tugatilgan" deb saqlanadi; kupon raqami eslab qolinishi shart emas —
> faqat nomer va uning yakuniy holati muhim (Q26).

---

## 7. ADMIN TOMONIDAN SOZLANADIGAN MATNLAR (Q16, Q17, Q19, Q20)

Bu yerda muhim **ikki xil** matn to'plami bor — buni ajratish shart (Q47 — TASDIQLANGAN):

### 7.1. Botni TANISH shablonlari (Teleton botni tushunishi uchun)
Bot qora quti, shuning uchun uning chiqishini tanib olish kerak. Adminbot orqali
**majburiy** kiritiladi (kiritilmasa -> tizim STOP + sabab yozadi, Q16):
1. Bot **"kupon so'ragan"** xabari namunasi
2. Bot **"muvaffaqiyatli/tasdiqlandi"** xabari namunasi
3. Bot **"muddati o'tgan"** xabari namunasi
4. Bot **"rad etildi"** xabari namunasi (agar bo'lsa)

### 7.2. MIJOZGA yuboriladigan shablonlar (o'z uslubingizda, Q20)
Adminbot orqali tasdiqlanadi:
1. **Kupon so'rash** matni (bot kupon so'ragach mijozga)
2. **Tasdiqlandi** matni
3. **Rad etildi** matni
4. **Muddati o'tgan** matni ("boshqa kupon yuboring")
5. **Rasm xato** matni ("kod ko'rinishida yuboring")
6. **Nomer band (DUPLICATE_ACTIVE)** matni — oldingi jarayon tugamagan (2.3)
7. **Allaqachon tasdiqlangan (ALREADY_CONFIRMED)** matni (2.4)

> Barcha shablonlar boshlang'ich (default) qiymat bilan keladi (10-bo'lim,
> mock bot javoblariga mos), lekin adminbot orqali istalgan vaqtda
> o'zgartirilishi mumkin (Q52 — TASDIQLANGAN).

---

## 8. AVTOMATLASHTIRISH DARAJASI (Q18, Q21)

**To'liq avtonom + istisnoda admin.** Ya'ni:
- Bot javobi aniq (tasdiq/rad/muddati o'tgan) -> Teleton **avtomatik** hal qiladi.
- Faqat quyidagilar admin oldiga tushadi (`NEEDS_ADMIN`):
  - Bot javobi tanilmagan/noaniq format
  - Shubhali holat (bir nomer ko'p akkaunt)
  - Rasm/xato kiritish (warning)
  - Timeout (bot javob bermadi)
- CONFIRMED bo'lganda mijozning lichkasiga ham "ishingiz tasdiqlandi" xabari
  avtomatik boradi (Q18).

---

## 9. ADMINBOT — FUNKSIYALAR

### 9.1. Bildirishnomalar (Q23 — sozlanadigan)
- Sukut: faqat **muhim** hodisalar (tasdiq / rad / xato / shubha / timeout).
- "Batafsil rejim" yoqilsa: har bir hodisa.

### 9.2. Buyruqlar
| Buyruq | Vazifa |
|---|---|
| `drop find <nomer>` | Nomer bo'yicha holatni ko'rish (`998881910` formatida) — Q26 |
| `/stats` | Statistika (10-bo'lim) |
| `/bots` | Tekshiruv botlari ro'yxati va holati |
| `/addbot` | Yangi tekshiruv boti qo'shish |
| `/templates` | Mijoz/bot shablonlarini ko'rish/tahrirlash |
| `/pending` | Javob kutayotgan case-lar |
| `/problems` | Muammoli / admin kutayotgan case-lar |

### 9.3. Tezkor amallar (inline tugmalar)
- Warning/shubha xabarlarida: `[Lichkaga o'tish]`, `[Xavfsiz]`, `[Bloklash]`
- Noaniq natijada: `[Tasdiqlash] [Rad] [Qayta uzatish]`

### 9.4. Sozlash oqimi (Q16)
- Bot shablonlari kiritilmagan bo'lsa, tizim ishga tushmaydi va adminbotga
  aniq sabab yozadi: *"Bot 'kupon so'rash' shabloni kiritilmagan — tizim to'xtatildi."*

### 9.5. Nomer/kupon yuborish formati (Q53 — TASDIQLANGAN)
Har bir tekshiruv bot uchun **alohida format sozlamasi** bo'ladi (`/bots`
buyrug'i ichida), chunki turli botlar turlicha kutishi mumkin:
- Nomer formati: `+998XXXXXXXXX` / `998XXXXXXXXX` / `XXXXXXXXX` (tanlovdan biri).
- Kupon formati: xom holicha (6 xonali raqam, o'zgarishsiz).
- Bot qo'shilganda (`/addbot`) admin shu formatni ko'rsatadi; standart qiymat
  `+998XXXXXXXXX`.

---

## 10. STATISTIKA (Q30)

- Kunlik murojaatlar soni
- Har bir lichka (admin) orqali nechta kupon o'tkazilgan
- Qaysi admin nechta kuponni tasdiqlagan
- CONFIRMED / REJECTED / TIMEOUT sonlari
- Muammoli holatlar soni

---

## 10.1. MOCK (SOXTA) TEST BOT — standart matnlar (Q52 — TASDIQLANGAN)

MVP-1/MVP-2 uchun quyidagi standart matnlar bilan soxta bot yasalади (real
botga ulanganда bularning o'rniga 7.1-bo'limdagi haqiqiy shablonlar kiritiladi):

| Vaziyat | Mock bot javobi (namuna) |
|---|---|
| Nomer qabul qilingandan keyin | `Kupon raqamini yuboring.` |
| Kupon to'g'ri va yangi | `✅ Muvaffaqiyatli! Kupon tasdiqlandi.` |
| Kupon muddati o'tgan | `⛔ Kuponning muddati o'tgan.` |
| Kupon noto'g'ri/mavjud emas | `❌ Bunday kupon topilmadi.` |

> Bu matnlar faqat **test/mock** uchun kod ichida standart qiymat sifatida
> yoziladi. Adminbot orqali istalgan vaqtda o'zgartirilishi mumkin (moslama
> `/templates` orqali) — real botga ulanganda aynan o'sha botning haqiqiy
> so'zlariga moslab qayta kiritiladi.

---

## 11. MA'LUMOTLAR MODELI (13a — kengaytirilgan CRM tizimi)

Siz 13a-da alohida to'liq tizim so'radingiz. Mana ideal model:

### 11.0. Ko'rish huquqi (Q51 — TASDIQLANGAN)
- Oddiy **admin (operator)** faqat o'ziga biriktirilgan (`assigned_admin_id`)
  mijozlar va case-larni ko'radi/qidiradi — boshqa adminning mijozlari
  ko'rinmaydi (na adminbotda, na keyingi panelda).
- **Owner** va **Rop** — hammasini ko'radi (14-bo'lim).

### 11.1. `users` (mijozlar) — CRM yadrosi
| Ustun | Izoh |
|---|---|
| id | ichki ID |
| tg_user_id | telegram ID |
| tg_username | @niki |
| display_name | lichkadagi ismi |
| phone | asosiy/oxirgi nomer |
| assigned_admin_id | **biriktirilgan admin** |
| is_safe | shubhadan tozalanganmi |
| is_blocked | bloklanganmi |
| first_seen / last_seen | vaqtlar |
| note | admin izohi (CRM) |

### 11.2. `cases` (murojaatlar)
| Ustun | Izoh |
|---|---|
| id | case ID |
| user_id | kim |
| phone | nomer |
| current_coupon | joriy kupon (o'zgarishi mumkin) |
| status | 6-bo'limdagi status |
| assigned_admin_id | qaysi admin yuritdi |
| bot_id | qaysi tekshiruv boti ishlatildi |
| confirmed_at | tasdiqlangan vaqt |
| created / updated | vaqtlar |

### 11.3. `coupon_attempts` (kupon urinishlari — expired tarixi)
| Ustun | Izoh |
|---|---|
| id | |
| case_id | qaysi case |
| coupon | urinilgan kupon |
| result | CONFIRMED / EXPIRED / REJECTED |
| bot_id | qaysi bot |
| created_at | vaqt |

### 11.4. `bots` (tekshiruv botlari)
| Ustun | Izoh |
|---|---|
| id / username | bot |
| is_active | yoqilgan |
| is_busy | hozir band |
| current_case_id | hozir qaysi case |
| total_processed | jami o'tkazgan |
| last_used_at | LRU uchun |

### 11.5. `admins`, `templates`, `bot_patterns`, `audit_log`, `relay_log`
- `admins` — rol (owner/rop/dasturchi/admin), telegram session
- `templates` — mijozga yuboriladigan matnlar
- `bot_patterns` — botni tanish shablonlari
- `audit_log` — kim nima o'zgartirdi
- `relay_log` — har bir uzatish izi

### 11.6. Qidiruv / filtr / statistika (13a talabi)
- Nomer, admin, status, sana bo'yicha filtr.
- Har adminning yiqqan kuponlari statistikasi.
- Mijozlar ro'yxati va tarixi (CRM ko'rinishi).

---

## 12. ISHONCHLILIK (Q36, Q37)

- **Timeout/retry:** bot javob bermasa 3 marta (backoff), keyin `TIMEOUT` + alert.
- **Restart reconciliation (Q37):** tizim qayta ishga tushganda yarim qolgan
  case-larni ko'rib chiqadi. Ba'zilari aslida yakunlangan bo'lishi mumkin ->
  ularni "ehtimol tasdiqlangan" deb belgilab, adminbotga ko'rib chiqish uchun yuboradi.
- **Bot band qolib ketsa:** case timeout bo'lsa bot majburan bo'shatiladi (lane leak oldini olish).

### 12.1. Tizim xatoliklari (crash / kutilmagan xato) — Q42 TASDIQLANGAN
Biznes-jarayon holatlaridan (TIMEOUT, EXPIRED va h.k.) farqli — bu **kod/tizim
darajasidagi** xatolik (DB ulanmadi, Telethon uzildi, kutilmagan exception):
- Har doim **log faylga** yoziladi (strukturali, sana-vaqt bilan).
- **Kritik** xatoliklarda (Teleton uzilib qoldi, DB yozib bo'lmadi) qo'shimcha
  ravishda **adminbotga darhol push** ketadi.
- Ikkovi ham baravar ishlaydi (Q42 javobingiz — "ikkovi").

---

## 12.2. XAVFSIZLIK VA MAXFIYLIK (Q12 va boshqalar — v1 dan tiklandi)

1. **Telefon raqami:** shifrlash/maskalash **shart emas** (Q12 — siz tasdiqladingiz).
2. **Adminbotga kirish:** faqat `admins` jadvalidagi ro'yxatdagi Telegram
   ID-lar buyruq bera oladi — boshqa hech kim.
3. **Sirlar (API_HASH, bot tokenlari, DB parol):** kodga yozilmaydi, `.env`
   faylida saqlanadi, git-ga tushmaydi.
4. **Audit:** har bir admin harakati (shablon o'zgartirish, blok, tasdiqlash)
   `audit_log`-ga yoziladi (11.5-bo'lim) — kim, qachon, nima qildi.
5. **Telegram ToS:** Teleton (Telethon) shaxsiy akkauntlarga ulanadi — test
   rejimida ohista, flood-limitlarga rioya qilib ishlatiladi.

## 12.3. ATAYLAB MVP-DAN TASHQARIDA QOLDIRILGANLAR (scope exclusions)

Quyidagilar siz tomonidan **ongli ravishda** keyinga qoldirilgan — bu
"unutilgan" emas, balki hozircha kerak emas deb qaror qilingan:
- **Rate-limit** (bir foydalanuvchi necha soniyada nechta murojaat) — Q34: *"keyinchalik o'ylab chiqamiz, MVP-da kerak emas."*
- **Avtomatik blacklist** (qoidalar asosida o'z-o'zidan bloklash) — Q35: *"kerak emas."*
- **Umumiy shubha-aniqlash tizimi** (rule engine, ball tizimi) — Q22: *"keyin ishlab chiqamiz, hozircha shunday qolsin."*
  (Eslatma: FAQAT bitta aniq shubha turi — "bir nomer turli akkauntlardan" —
  5.2-bo'limda **hozir ham ishlaydi**; bu yerda gap kelajakdagi qo'shimcha,
  kengroq shubha turlari haqida.)

---

## 13. TEXNOLOGIYA VA INFRA (Q31, Q38, Q39, Q40, Q41)

| Qatlam | Tanlov |
|---|---|
| Teleton | Python, **Telethon**, asyncio, **multi-account** (har admin alohida session) |
| Adminbot | Python, **aiogram 3.x** |
| DB | **SQLite** (boshda) -> keyin PostgreSQL (kod ko'chishga tayyor) |
| Panel | Keyinchalik (FastAPI + web) |
| Deploy | Test: lokal kompyuter. Keyin: **Docker Compose**, alohida jarayonlar (mikroservis) |
| Til | Faqat **o'zbekcha** (matnlar alohida faylda) |
| Test | **Soxta (mock) bot** bilan sinov, keyin real botlar |
| Backup | **Kunlik avtomatik SQLite fayl nusxasi** boshqa papkaga (Q60 — TASDIQLANGAN) |
| Saqlash | **Doimiy** (o'chirilmaydi, Q32) |

### 13.1. Mikroservis tuzilishi
```
teleton-service     (Telethon, ko'p akkaunt, bot pool)
adminbot-service    (aiogram)
core (umumiy)       (DB, modellar, biznes-logika)
panel-service       (keyin)
   -- hammasi bitta SQLite/DB ni baham ko'radi
```

---

## 14. ROLLAR (Q25, Q43) — keyin batafsil

- **Owner** — hammasi
- **Rop (boshliq)** — statistika, adminlar nazorati, hisobotlar
- **Dasturchi** — texnik sozlash, botlar, shablonlar
- **Admin (operator)** — o'z lichkasi, o'z case-lari
- **Kuzatuvchi (viewer)** — faqat ko'rish

Har biri adminbot/panelda o'z roliga mos ko'rinishni ko'radi (Q43). Aniq
bo'linish loyiha to'liq oydinlashgach hal qilinadi.

---

## 15. BAJARILISH BOSQICHLARI (yangilangan)

| Bosqich | Ish |
|---|---|
| **MVP-1** | Teleton + SQLite + bot pool + asosiy oqim (nomer->kupon->natija) — **mock bot bilan** |
| **MVP-2** | Adminbot: bildirishnoma, `drop find`, shablon sozlash, bot qo'shish |
| **MVP-3** | Expired qayta oqim, shubha/warning, rasm-xato, timeout/retry |
| **MVP-4** | Statistika, reconciliation, audit log |
| **MVP-5** | Real botlarga ulash, ko'p akkaunt, Docker |
| **MVP-6** | Web panel |

---

## 16. SAVOLLAR

### Hal bo'lgan (v2.1)
- **Q45** — Hamma bot band -> navbatda kutsin + admin alert. TASDIQLANGAN
- **Q47** — Ikki xil matn to'plami alohida (botni tanish + mijozga yuborish). TASDIQLANGAN
- **Q48** — Mijoz 5 daqiqada kupon yubormasa -> seans to'xtaydi, bot bo'shaydi;
  kech yuborsa "nomerni qaytadan yuboring". TASDIQLANGAN
- **Q13** — Bot qora quti, o'zgartirib bo'lmaydi, 5–10 ta bot galma-gal
  ishlatiladi. TASDIQLANGAN (3-bo'lim shu asosda yozildi)
- **Q49** — Faol case bor holatda yangi nomer kelsa: botga yuborilmaydi,
  mijozdan aniqlashtiriladi + adminga darhol xabar (2.3-bo'lim). TASDIQLANGAN
- **Q50** — Tasdiqlangan nomer qayta kelsa: botga yuborilmay avtomatik rad
  javobi ("allaqachon tasdiqlangan", 2.4-bo'lim). TASDIQLANGAN
- **Q51** — Har admin faqat o'ziniki, Owner/Rop hammasini ko'radi (11.0-bo'lim). TASDIQLANGAN
- **Q52** — Mock bot uchun standart matnlar men tomonimdan yozildi
  (10.1-bo'lim), adminbot orqali o'zgartiriladigan. TASDIQLANGAN
- **Q46** — Qat'iy O'zbekiston formati: uzunlik + haqiqiy operator kodi
  (4.1-bo'lim). TASDIQLANGAN
- **Q53** — Format har bot uchun alohida sozlanadi, standart `+998XXXXXXXXX`
  (9.5-bo'lim). TASDIQLANGAN

### Hali aniq emas — MVP jarayonida real bot bilan aniqlanadi

**Q54.** Tekshiruv botlari bilan avval `/start` bosib suhbat ochish kerakmi,
yoki ular allaqachon Teleton akkauntlari bilan suhbatda bormi?
> MVP-1/2 da mock bot bilan bu masala yo'q. MVP-5 (real botlarga ulash)
> bosqichida aniqlanadi — kerak bo'lsa `/addbot` jarayoniga "avval /start bos"
> qadami qo'shiladi.

**Q55.** *(Ko'p akkaunt bosqichi uchun)* Bitta tekshiruv boti bir nechta admin
akkaunti bilan parallel ishlay oladimi? Bitta botga umumiy limit kerakmi?
> Xavfsiz standart: **har admin+bot juftligi mustaqil slot** hisoblanadi (ya'ni
> N admin bo'lsa, har biri o'z nusxasidagi bot pool-ini ishlatadi — bir-biriga
> aralashmaydi). MVP-5 da ko'p akkaunt qo'shilganda haqiqiy chеklov kerakmi
> tekshiriladi.

**Q56.** REJECTED (rad etildi) va EXPIRED (muddati o'tgan) — bot ikkovini
farqlab beradimi, yoki ikkovi bir xil ko'rinadimi?
> "Bilmayman, keyin aniqlashtiramiz" — TZ hozircha ikkovini **alohida status**
> deb saqlaydi (6-bo'lim), chunki bu arzon zaxira (keraksiz bo'lsa keyin
> birlashtirish oson). Real bot bilan sinaganda agar bot farqlamasa, ikkovini
> bitta `REJECTED` ga birlashtiramiz — kod tuzilishi buni qiyinchiliksiz
> qo'llab-quvvatlaydi.

### Yangi hal bo'lganlar (chuqur audit, v2.1 tekshiruvi)
- **Q57** — EXPIRED da bot darhol bo'shaydi, mijoz qayta nomer yuborganda
  yangi urinish sifatida pool dan istalgan bo'sh bot tanlanadi. TASDIQLANGAN
  (2.1, 3.1, 3.5-bo'limlar yangilandi).
- **Q58** — Qayta yuborilgan kupon eskisi bilan bir xil bo'lsa, Teleton botga
  yubormay "boshqa kupon kerak" deb qaytaradi. TASDIQLANGAN (2.1-bo'lim).
- **Q59** — EXPIRED-qayta-urinish sikli maksimal **5 marta**, keyin
  `NEEDS_ADMIN`. TASDIQLANGAN (2.1-bo'lim).
- **Q60** — Backup kerak: kunlik avtomatik SQLite fayl nusxasi. TASDIQLANGAN
  (13-bo'lim).

**Q61.** `coupon_attempts` jadvalida (11.3) har bir urinilgan kupon **qiymati**
tarixiy saqlanadi (audit uchun). Sizning 26-punkt javobingizda "kupon
raqamini eslab qolish kerak emas" degansiz — bu faqat adminning `drop find`
paytida ko'radigan narsasiga tegishlimi (u faqat holat va nomerni ko'radi),
yoki bazada ham kupon tarixini umuman saqlamaslik kerakmi?
