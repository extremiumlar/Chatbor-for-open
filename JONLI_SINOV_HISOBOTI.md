# Jonli sinov hisoboti — TZ v2 (Qo'lda Admin Oqimi)

**Sana:** 2026-08-16
**Usul:** 3 ta haqiqiy Telegram test akkaunti bilan Telethon orqali jonli sinov
**Tekshirilgan hujjat:** `TZ_v2_Qolda_Admin_Oqimi.md`

## Sinov muhiti

| Rol | Akkaunt | Tizimdagi o'rni |
|---|---|---|
| **Admin** | `@abduqahhor_suvonov` (6644467393) | `admin_1` sessiyasi, OWNER |
| **Mijoz** | `@NB_IT_bolim` (8848866228) | `admin_2` sessiyasi, ADMIN |
| **Tekshiruvchi** | `@cheklanma` (6903942240) | `admin_3` sessiyasi, `CHECKER_ACCOUNT` |
| Nazorat guruhi | `-1004363150995` | `GROUP_CHAT_ID` |
| Adminbot | `@O_B_adminsbot` | — |

Sinov davomida yaratilgan haqiqiy ma'lumot: **C7–C10 case'lari, 6 ta rasm
partiyasi, 5 ta tekshiruv so'rovi**, guruhda ~30 ta post.

> ⚠️ **Sinov vositasining cheklovi:** mijoz va tekshiruvchi rollari ham
> tizimga admin sifatida ulangan akkauntlar. Bu ba'zi hodisalarni ikki
> marta ko'rinishiga sabab bo'ldi — quyida qayerda shunday bo'lgani aniq
> yozilgan (M-1 topilmasiga qarang).

---

# 🔴 Jiddiy (jonli rejimga o'tishdan OLDIN tuzatilishi shart)

## K-1. `/shadow` argumentsiz yozilganda soya rejimini O'CHIRIB YUBORADI

**Fayl:** `adminbot_service/bot.py:2207` (`cmd_shadow`)

`/shadow` buyrug'i **holatni ko'rsatmaydi — har safar almashtiradi (toggle)**.
Admin "hozir qaysi rejimdaman?" deb yozgan `/shadow` xavfsizlik tormozini
jimgina o'chiradi.

**Jonli dalil (2 marta, ikkala kod versiyasida ham takrorlandi):**

```
>> /shadow
   javob: 🟢 Soya rejimi O'CHIRILDI — natijalar endi mijozlarga yetkaziladi
```

Audit jurnali: `admin 6644467393 → shadow_mode → off` (21:45:43 va 21:51:51).

**Nega jiddiy:** TZ §6.4.6 soya rejimini "birinchi kunlar uchun xavfsizlik
tormozi" deb belgilaydi. Bu tormoz **bitta tasodifiy buyruq bilan** ochiladi
va admin buni sezmasligi mumkin — keyingi "O'TDI" natijasi haqiqiy mijozga
ketadi.

**Izchillik buzilishi:** `/setreporttime` argumentsiz yozilganda joriy
qiymatni ko'rsatadi (`Joriy hisobot vaqti: 01:30`). `/shadow` esa
o'zgartiradi — bir xil bot ichida ikki xil mantiq.

**Tavsiya:** `/shadow` → holat + `/shadow on|off` → o'zgartirish.

---

## K-2. Soya rejimi mijozga ketadigan IKKI xabarda hurmat qilinmaydi

**Fayllar:**
- `teleton_service/manual_relay.py:321-332` — §5.3 "tekshirish jarayonida" shabloni
- `teleton_service/manual_relay.py:392-395` — §6.1a4 `ALREADY_CONFIRMED` javobi

TZ §6.4.6: soya rejimi = *"tizim taniydi, bazaga yozadi, guruhga reaksiya
qo'yadi — lekin **mijozga hech narsa yozmaydi**"*.

**Jonli dalil** (`SHADOW_MODE = 1` bo'lgan holda mijoz lichkasiga kelgan):

```
CUST 2848  'Kuponingiz tekshirish jarayonida. Iltimos, 1.5 soatdan keyin eslating.'
CUST 2852  'Kuponingiz tekshirish jarayonida. Iltimos, 1.5 soatdan keyin eslating.'
CUST 2915  'Kuponingiz tekshirish jarayonida. Iltimos, 1.5 soatdan keyin eslating.'
CUST 2909  'Bu nomerdan oldin ovoz berilgan'
```

**Muhim nuance:** `core/logic/result_flow.py` soya rejimini **to'g'ri**
tekshiradi (natija xabarlari mijozga ketmadi ✅). Muammo faqat relay
qatlamida — u `is_shadow_mode()` ni umuman chaqirmaydi.

**Tavsiya:** `process_batch` va `on_incoming` da ham `is_shadow_mode()`
tekshiruvi.

---

## K-3. Joriy shablon sozlamasida SALBIY javob "O'TDI" deb tanilmoqda

**Jonli dalil (`/testcheck` orqali, TZ §6.4.6 vositasi):**

| Tekshiruvchi yozsa | Tizim tanidi | Bo'lishi kerak |
|---|---|---|
| `bazada bor emas` | ✅ **O'TDI** | ❌ O'TMADI |
| `bor emas` | ✅ **O'TDI** | ❌ O'TMADI |
| `o'tmadi` | ❓ tanilmadi | ❌ O'TMADI |
| `O'TMADI` / `o‘tmadi` | ❓ tanilmadi | ❌ O'TMADI |
| `yo'q` | ❓ tanilmadi | ❌ O'TMADI |
| `topilmadi` | ❓ tanilmadi | ❌ O'TMADI |
| `o'tdi` | ❓ tanilmadi | ✅ O'TDI |
| `✅` | ❓ tanilmadi | ✅ O'TDI |
| `прошел` / `нет` | ❓ tanilmadi | PASSED / FAILED |

**Sabab — kod emas, SOZLAMA.** Joriy shablonlar:

```
CHECK_PATTERNS_PASSED = ["bor"]
CHECK_PATTERNS_FAILED = ["otmadi"]        <-- apostrofsiz, tabiiy emas
CHECK_PATTERNS_ERROR  = ["tizimda nosozlik keyin urinib ko'ring"]
```

`o'tmadi` (tabiiy yozilish) `otmadi` shabloniga mos kelmaydi. Natijada
§6.4.3 dagi "avval SALBIY tekshiriladi" himoyasining **ishga tushadigan
shabloni yo'q**, va "bor emas" ichidagi "bor" g'olib chiqadi.

**Dvigatelning o'zi TO'G'RI** — buni isbotladim: to'liq shablon
(`o'tmadi`, `~bor emas`, `yo'q`, `topilmadi`, `o'tdi`, `=✅`) qo'shilganda:

```
'bazada bor emas'     -> ❌ O'TMADI    (qamrab olish qoidasi ishladi)
'O‘TMADI'             -> ❌ O'TMADI    (katta harf + boshqa apostrof)
'o'tdi yoki o'tmadi'  -> ⚠️ QARAMA-QARSHI -> NEEDS_ADMIN
'borligi tasdiqlandi' -> ❓ tanilmadi  (butun so'z qoidasi to'g'ri)
```

*(Qo'shilgan shablonlar sinovdan keyin O'CHIRILDI — sozlama boshlang'ich
holatiga qaytarildi.)*

**Nega jiddiy:** soya rejimi o'chgan zahoti ovozi **o'tmagan** mijozga
"o'tdi" deb yoziladi. K-1 bilan birga bu real xavf.

**Tavsiya:** jonli rejimga o'tishdan oldin har uch kategoriyaga real
javob variantlarini kiritish (lotin/kirill, apostrofli/apostrofsiz,
emoji). §6.4.6 dagi "tanilmagan javoblar jurnali" shu uchun mavjud.

---

## K-4. `/checkpatterns` buyrug'i relay tomonidan yeb qo'yiladi va O'CHIRILADI

**Fayl:** `teleton_service/manual_relay.py:493`

```python
if text.lower().startswith("/check"):
```

`startswith("/check")` `/checkpatterns` va `/checkpattern` ni ham qamrab
oladi. Relay bu xabarni `/check` deb qabul qiladi va **birinchi navbatda
o'chiradi** (`event.message.delete(revoke=True)`).

**Jonli dalil (3/3 urinish):**

```
'/checkpatterns'                 -> xabar O'CHIRILDI, adminbot javob bermadi
'/checkpattern sinov'            -> xabar O'CHIRILDI
'/checkpatterns@O_B_adminsbot'   -> xabar O'CHIRILDI
   har birida: "⚠️ /check — nomer topilmadi. Nomerli xabarga reply qiling..."
'/testcheck bor'                 -> turibdi ✅ (prefiks boshqacha)
```

**Nega jiddiy:** TZ arxitekturasi bo'yicha **har bir adminning akkauntida
Telethon sessiyasi ishlaydi** — demak `/checkpatterns` amalda **hech kim
uchun ishlamaydi**. `permissions.py` da bu buyruq hamma rolga ochiq deb
yozilgan, lekin amalda ochiq emas.

**Tavsiya:** aniq moslik — `text.split()[0].lower() == "/check"` (yoki
`@bot` qo'shimchasini hisobga olgan holda).

---

## K-5. Nazorat guruhi adminbot javoblari bilan to'ldirib tashlanadi

**Fayl:** `adminbot_service/bot.py:169-181` (`IsAdmin`), `:2382` (`on_unknown`)

`IsAdmin` filtri faqat **xabar yuboruvchi admin ekanini** tekshiradi —
chatning **lichka ekani tekshirilmaydi**. Nazorat guruhida forward
qilingan rasmlar (admin akkauntidan ketadi) va caption (ichida nomer bor)
adminbotni ishga tushiradi.

**Jonli dalil — har bir rasm partiyasidan keyin guruhda:**

```
GROUP 66 OUT [PHOTO]                          <- forward
GROUP 67 OUT [PHOTO]                          <- forward
GROUP 68 OUT '📸 #C7 ... +998 90 111 22 33'   <- caption
GROUP 69 IN(bot) "Tushunmadim 🤔 ..."          <- CHIQINDI
GROUP 70 IN(bot) "Tushunmadim 🤔 ..."          <- CHIQINDI
GROUP 71 IN(bot) '🔍 998901112233 — 2 ta murojaat:'  <- CHIQINDI
```

Sinov davomida guruhda **12+ shunday chiqindi xabar** to'plandi. Har
partiya = 3 ta ortiqcha xabar. TZ §8.3 dagi kunlik 47 nomer bo'yicha
hisoblasak — **kuniga ~140 ta chiqindi xabar**, arxiv o'qib bo'lmas
holga keladi.

**Tavsiya:** `admin_router.message.filter(F.chat.type == "private")` va
guruhda faqat `/setgroup` kabi ataylab guruh uchun mo'ljallangan
buyruqlarni qoldirish.

---

# 🟠 O'rta

## M-1. Boshqa ADMIN akkauntidan kelgan nomer mijoz nomeri deb qabul qilinadi

**Fayl:** `teleton_service/manual_relay.py:346-418` (`on_incoming`)

`on_incoming` da **tekshiruvchi** uchun himoya bor (`_is_checker`,
nomer aniqlashdan oldin turadi ✅), lekin **boshqa adminlar uchun
himoya yo'q**.

**Jonli dalil 1:** admin_1 boshqa admin lichkasiga nomer yozdi →
`C8` case'i ochildi, admin_1 **mijoz** sifatida ro'yxatga tushdi
(`user_id=4`), SHUBHALI alert ketdi.

**Jonli dalil 2 (muhimroq):** tekshiruvchiga yuborilgan
`+998935556677` so'rovi tekshiruvchining **o'z relay klienti** tomonidan
kiruvchi mijoz xabari deb o'qildi:

```
Mijoz (tg_id=6644467393) ikkinchi nomer yubordi (998935556677),
lekin C8 (998901112233) hali ochiq (SUSPICIOUS_HOLD).
```

**Konfiguratsiya xavfi:** agar tekshiruvchi akkaunti ayni vaqtda
kuzatilayotgan admin ham bo'lsa (`/setchecker` buni taqiqlamaydi),
**har bir tekshiruv so'rovi** soxta case/alert yaratadi.

**Tavsiya:** `on_incoming` da yuboruvchi `admins` jadvalida bo'lsa —
e'tiborsiz qoldirish; `/setchecker` da tekshiruvchi admin sessiyasi
bo'lsa ogohlantirish.

---

## M-2. Faqat OXIRGI partiya natija oladi — oldingi guruh postlari belgisiz qoladi

**Fayl:** `core/logic/result_flow.py:235-240`

```python
.order_by(ScreenshotBatch.id.desc())
batch = result.scalars().first()      # faqat bitta
```

**Jonli dalil** — C7 case'ida 3 ta partiya bor edi, natija PASSED chiqdi:

| Partiya | Guruh posti | outcome | Reaksiya |
|---|---|---|---|
| #1 | 56 | `PENDING` | yo'q |
| #2 | 62 | `PENDING` | yo'q |
| #3 | 68 | `PASSED` | 👍 |

TZ §6.1a bo'yicha **admin rasmni qayta tashlashi normal holat**
("taymer oxirgi rasm vaqtidan qayta hisoblanadi"). Demak arxivda
belgisiz postlar qolishi muntazam hodisa bo'ladi, va §8.2 dagi
`screenshot_batches.outcome` statistikasi buziladi.

**Tavsiya:** case'ning barcha partiyalarini yangilash (yoki hech
bo'lmaganda `is_duplicate=False` bo'lganlarini).

---

## M-3. Dublikat ogohlantirishi bir xil admin/case uchun ham chiqadi, matni chalg'itadi

**Fayl:** `core/logic/screenshots.py:107-119`, `:159-166`

Dublikat faqat **nomer** bo'yicha aniqlanadi — case va admin hisobga
olinmaydi. Natijada admin **o'sha mijozga** ikkinchi marta rasm tashlasa
ham dublikat deb belgilanadi.

**Jonli dalil:**

```
⚠️ DUBLIKAT: +998 90 111 22 33 uchun avval ham rasm tashlangan
(partiya #1, admin_id=1). Yangi partiya: C7 (admin: 6644467393).
Ikki admin bitta mijoz ustida ishlayotgan bo'lishi mumkin.
```

Bu yerda admin ham, case ham **bitta** — xabar noto'g'ri. Caption'da esa
post o'z case'iga havola qiladi:

```
⚠️ Bu nomer uchun avval ham rasm tashlangan — #C7 (Admin: ..., 02:25)
```

TZ §5.4 dagi namuna **boshqa** case'ga havola qiladi (`#C1189`).

**Tavsiya:** `case_id` bir xil bo'lsa dublikat deb belgilamaslik, yoki
alert matnini ajratish ("o'sha case'ga qayta rasm" ≠ "ikki admin").

---

## M-4. `/stats` oddiy adminga butun tizim ma'lumotini ko'rsatadi (§8.4 buzilishi)

**Jonli dalil** — `@NB_IT_bolim` (rol: `ADMIN`) yubordi:

```
📊 Statistika
Bugungi murojaatlar: 2          <- ikkalasi ham emas, biri admin_1 niki
Ochiq muammoli holatlar: 2
Holat bo'yicha (barcha vaqt):
  CHECK_SENT: 1                 <- admin_1 ning C7 case'i
  ❌ Rad etildi: 3
  🕵️ Shubhali: 1
```

TZ §8.4: *"**Oddiy admin** — faqat o'z statistikasini ko'radi"*.

`/vstats` bu qoidani **to'g'ri** bajaradi (`(faqat sizniki)` deb yozadi ✅),
`/problems` ham to'g'ri cheklangan ✅ — faqat eski `/stats` ekrani ochiq.

**Qo'shimcha:** `/stats` oxirida eskirgan v1 matni turibdi:
*"Har admin bo'yicha alohida taqsimot ko'p akkaunt ishga tushganda
qo'shiladi (hozircha bitta Teleton akkaunti ishlaydi)"* — aslida
**3 ta** sessiya ishlayapti.

---

## M-5. TZ §4.3 talab qilgan "Sessiyalar" bo'limi adminbotda YO'Q

TZ §4.3: *"Adminbotda `Sessiyalar` bo'limi: har akkaunt holati, oxirgi
faollik vaqti."*

Qidiruv natijasi: bunday buyruq ham, tugma ham, `permissions.py` da
yozuv ham yo'q.

Baza qatlami **tayyor** — `admin_sessions` jadvalida `status`,
`last_seen_at`, `last_error` to'ldirilib turadi:

```
(1, 3, 'admin_3', '+998938461910', 'CONNECTED', '2026-08-16 05:42:24', None)
(2, 2, 'admin_2', '+998701980632', 'CONNECTED', '2026-08-16 05:42:23', None)
(3, 1, 'admin_1', '+998331718881', 'CONNECTED', '2026-08-16 05:42:22', None)
```

Sessiya uzilganda alert ham ishlaydi (arxivda ko'rindi:
`🔴 6903942240 (+998938461910) sessiyasi BEKOR QILINGAN`). Faqat
**ko'rish oynasi** qurilmagan.

---

## M-6. `permissions.py` jadvali handler ichidagi tekshiruvlarga ZID

`core/logic/permissions.py` o'z izohida **"yagona haqiqat manbai"** deb
yozilgan, lekin handler'lar o'z tekshiruvini yuritadi:

| Buyruq | `permissions.py` | Handler ichidagi tekshiruv |
|---|---|---|
| `/setgroup` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/setchecker` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/shadow` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/addcheckpattern` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/delcheckpattern` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |

**Oqibati:** `DASTURCHI` rolidagi odam bu buyruqlarni `/help` da
**ko'radi**, middleware uni **o'tkazadi**, lekin handler
*"Faqat Owner/Rop ..."* deb **rad etadi**. Aynan `permissions.py`
oldini olmoqchi bo'lgan holat.

*(Sinovda admin_1 OWNER bo'lgani uchun buyruqlar o'tdi; zidlik kod
darajasida aniq.)*

---

## M-7. Yagona OWNER'ni pasaytirish keyingi ishga tushishda jimgina bekor qilinadi

**Fayl:** `core/logic/admins.py:40-79` (`ensure_owner_exists`)

Foydalanuvchi `/setrole 6644467393 DASTURCHI` bajargan (audit #22,
21:08:02) va tasdiq olgan. Keyin qo'shimcha adminbot jarayoni ishga
tushganda `ensure_owner_exists` faol OWNER topmay, admin_1 ni
**qayta OWNER qildi**.

- Audit jurnaliga **yozilmaydi** (faqat `log.warning`)
- Adminga **xabar bermaydi**
- Natijada admin o'zini DASTURCHI deb o'ylab yuradi, aslida OWNER

Mexanizm o'zi to'g'ri (tizim qulflanib qolmasligi uchun), lekin
**ko'rinmasligi** muammo.

**Tavsiya:** ko'tarilganda `audit_log` ga yozish + superadminga xabar.

---

# 🟡 Kichik

## P-1. Guruh caption'ida admin RAQAM bo'lib ko'rinadi

**Jonli dalil (oldin / keyin):**

```
🧑‍💼 Admin: 6644467393              <- C7, C9 postlari
🧑‍💼 Admin: Abduqahhor Suvonov      <- C10 posti
```

Sabab: `refresh_admin_identity` (`core/logic/admins.py:102`) **faqat
adminbot middleware'idan** chaqiriladi (`bot.py:188`). Relay uni hech
qachon chaqirmaydi.

**Oqibati:** adminbotga hech qachon yozmagan admin barcha guruh
caption'larida raqam bo'lib qolaveradi. TZ §5.2 namunasi ism talab
qiladi (`🧑‍💼 Admin: Aziz Karimov`).

**Tavsiya:** `multi_client` sessiya ulanganda `get_me()` dan ismni
yangilash (ma'lumot allaqachon olinadi).

---

## P-2. Caption'da mijozga `tg://user?id=` havolasi yo'q

TZ §5.2: *"Mijozga havola: `tg://user?id=<tg_user_id>`"*.

Amalda (`core/logic/screenshots.py:257-263`) oddiy matn:

```
👤 @NB_IT_bolim (NB Dasturchi Nurullo)
```

Username bo'lmasa `id:6644467393` yoziladi — u ham bosiladigan havola
emas. Nazorat guruhida mijozga tez o'tish imkoni yo'qoladi.

---

## P-3. Kupon noto'g'ri case'ga yozilishi mumkin

**Fayl:** `core/logic/manual_case.py:131-155` (`handle_coupon_detected`)

Kupon **mijozning oxirgi ochiq case'iga** bog'lanadi — xabardagi
nomerga emas.

**Jonli dalil:** mijoz `907778899 kuponim 123456` yozdi. Nomer rad
etildi (C7 hali ochiq edi), lekin **kupon 123456 C7 ga
(998901112233) yozildi**:

```
(7, 'C7', '998901112233', 'NUMBER_RECEIVED', '123456', '2026-08-15 21:25:23')
```

TZ §9.2 kuponni "dalil" va "mijoz ovoz berganligi signali" deb
belgilaydi — noto'g'ri nomerga bog'langan kupon ikkala vazifani ham
buzadi (§6.1a2 dagi rasmsizlik eslatmasi noto'g'ri variantda chiqadi).

---

## P-4. Har partiyada mijozga §5.3 shabloni qayta yuboriladi

C7 uchun 3 ta partiya → mijozga bir xil matn **3 marta** ketdi
(yuqoridagi K-2 dalilига qarang). Admin bir necha marta rasm
tashlashi normal (§6.1a) — mijoz uchun bu spam.

---

## P-5. `pytest` ishlab turgan tizimning log fayliga yozadi

Tekshirildi: `pytest -q` dan oldin `logs/adminbot.log` = 180 834 bayt,
keyin = 189 391 bayt. Test uydirma ma'lumotlari jonli logga tushadi:

```
2026-08-16 10:41:07 | INFO | manual_case | Yangi case C1: nomer 998901111111, admin_id=1, tg_id=111.
2026-08-16 10:41:07 | INFO | screenshots | Partiya #1 qayd etildi: case=C1, admin=Aziz, rasm=2.
```

Baza ajratilgan ✅ (haqiqiy bazaga tegmaydi), faqat log aralashadi —
xato tekshirishda chalg'itadi.

---

# ✅ TZ bo'yicha TO'G'RI ishlagan qismlar

Bular jonli sinovda tasdiqlandi — ishonch bilan foydalanish mumkin:

| TZ bandi | Nima sinaldi | Natija |
|---|---|---|
| §3, §6.1 | Nomer aniqlash, case ochilishi, `short_code` | ✅ |
| §4.1 | Operator kodi filtri (`922223344` rad etildi) | ✅ |
| §5.1 | Albom (`grouped_id`) → bitta partiya | ✅ |
| §5.1 | 15 soniyalik oyna → 2 ta alohida rasm bitta partiya | ✅ |
| §5.1 | Ochiq case yo'q → rasm guruhga tushmadi | ✅ |
| §5.2 | Guruhga forward + caption, Toshkent vaqti (UTC+5) | ✅ |
| §5.5 | Nomersiz rasm → 30 daq kutish → nomer kelgach bog'landi | ✅ |
| §6.1a | Taymer **rasm vaqtidan** qayta hisoblandi, eski job yopildi | ✅ |
| §6.1a2 | Rasm kelgach rasmsizlik eslatmasi bekor qilindi | ✅ |
| §6.1a4 | `ALREADY_CONFIRMED` — o'tgan nomer qayta kelganda | ✅ |
| §6.1b | `/check` xabari **darhol o'chirildi** | ✅ |
| §6.1b | `/check` reply'dan va argumentdan nomer oldi | ✅ |
| §6.1b | Nomer/case topilmasa aniq xato xabari | ✅ |
| §6.1b | Ochiq so'rov bo'lsa ikkinchi `/check` rad etildi | ✅ |
| §6.2 | Drip navbat (20s), bazada saqlanadi | ✅ |
| §6.3 | So'rov **o'sha adminning akkauntidan** ketdi | ✅ |
| §6.4.2 | Normallashtirish: katta harf, apostrof variantlari | ✅ |
| §6.4.3 | Tartib + qamrab olish (to'liq shablon bilan) | ✅ |
| §6.4.3 | Butun so'z qoidasi (`borligi` ichidan `bor` topilmadi) | ✅ |
| §6.4.3 | Qarama-qarshi matn → `NEEDS_ADMIN` | ✅ |
| §6.4.5 | Bog'lash **FIFO** — eng eski ochiq so'rovga | ✅ |
| §6.4.5 | Bog'lash **oxirgi-4 raqam** (`2233 bor`) | ✅ |
| §6.4.5 | Bog'lash **reply** orqali | ✅ |
| §6.4.5 | Tanilmagan javob → kutildi, `raw_reply` ga yozildi | ✅ |
| §6.5 | Javobsizlik → `CHECK_STALLED` + alert | ✅ |
| §6.6 | Kesh — 10 daqiqa ichida qayta so'rov yuborilmadi | ✅ |
| §7.1 | PASSED → mijozga (soya rejimida to'xtatildi) | ✅ |
| §7.3 | Guruhga 👍 / 👎 avtomatik reaksiya | ✅ |
| §7.3 | **Qo'lda** reaksiya override → `MANUAL`, `reacted_by` yozildi | ✅ |
| §8.4 | `/vstats` va `/problems` ko'rish cheklovi | ✅ |
| §9.4, §11 | **Restart chidamliligi** (quyida alohida) | ✅ |
| §12 | Shubhali holat (bir nomer turli akkauntdan) | ✅ |
| §14 | `ADMIN` roli uchun barcha TECH/OWNER buyruqlar rad etildi | ✅ |

## Alohida ta'kidlash: restart chidamliligi haqiqiy sinovdan o'tdi

Sinov o'rtasida kompyuter uyquga ketib, **ikkala xizmat ham ~7.5 soat
o'chib qoldi** (`teleton_v2.log` 03:01 da uzilgan, xatosiz).

Qayta ishga tushirilgandan so'ng:

```
10:42:24 | multi_client | Admin ... (id=1) sessiyasi ulandi: admin_1
10:42:24 | multi_client | Admin ... (id=2) sessiyasi ulandi: admin_2
10:42:24 | multi_client | Admin ... (id=3) sessiyasi ulandi: admin_3
10:42:24 | manual_relay | Teleton v2 ishga tushdi: 3 ta admin sessiyasi ulandi.
```

Muddati o'tib ketgan `STALLED_ALERT` (rejalashtirilgan 22:30:12) darhol
bajarildi (`done_at = 05:42:55`), `C9` → `CHECK_STALLED`, ochiq so'rov
navbatda saqlandi. **Hech narsa yo'qolmadi** — TZ §9.4 va §11
talabi amalda tasdiqlandi.

> Eslatma: xizmatlar o'zi ko'tarilmadi (Windows'da nazoratchi yo'q).
> TZ §13.3 dagi `systemd` + `Restart=always` rejasi aynan shu uchun
> kerak — VDS'da bu muammo bo'lmaydi.

**Birlik testlar:** `291 passed` (15.1 s) ✅

---

# Sinalmagan qismlar

Bular jonli sinovdan **o'tmadi** — VDS'da alohida tekshirish kerak:

| TZ bandi | Nima | Sabab |
|---|---|---|
| §6.5 | Kech javob avtomatik to'g'irlanishi | Tabiiy yo'l bilan hosil qilib bo'lmadi. **Birlik test bor:** `tests/test_result_flow.py:214` |
| §7.1 | FAILED → `[Mijozga yuborish]` tugmasi | Soya rejimi bu oqimni butunlay to'sadi (kod: `result_flow.py:160-166`) |
| §4.2b | Nofaol admin → case'lar muzlatilishi | Admin o'chirilishi kerak edi |
| §4.4 | `FloodWaitError` bo'yicha throttling | Sun'iy hosil qilinmadi |
| §8.3 | Kunlik hisobot (guruh + superadmin) | Vaqt kelmadi (`DAILY_REPORT_TIME = 01:30`) |
| §5.4 | Ikki **turli** admin bitta nomerga rasm tashlashi | Ikkinchi admin sessiyasidan rasm yuborilmadi |
| — | 5+ akkaunt bilan parallel yuklama | Sinov muhitida 3 akkaunt |

---

# Sinov davomida kiritilgan va QAYTARILGAN o'zgarishlar

Shaffoflik uchun — tizimda nima o'zgartirilgani:

| O'zgarish | Holat |
|---|---|
| 6 ta tanish shabloni qo'shildi (K-3 ni isbotlash uchun) | ✅ **hammasi o'chirildi**, sozlama boshlang'ich holatda |
| `/shadow` tasodifan 2 marta o'chirdi (K-1 xatosi) | ✅ **ikkalasida ham `SHADOW_MODE = 1` ga qaytarildi** |
| Ortiqcha 2 ta jarayon to'xtatildi (v1 relay + ikkinchi adminbot) | ruxsat bilan |
| Adminbot qayta ishga tushirildi (eski kodda edi) | ruxsat bilan |
| Relay + adminbot uyqudan keyin qayta ishga tushirildi | ✅ ishlayapti |
| Test case'lari C7–C10, 6 partiya, 5 so'rov | bazada qoldi |

> Sozlamalar hozirgi holati tekshirildi: `SHADOW_MODE=1`,
> `CHECK_PATTERNS_*` — sinovdan oldingi qiymatlar bilan bir xil.

---

# Tavsiya etilgan tuzatish tartibi

**Jonli rejimga o'tishdan oldin (majburiy):**

1. **K-3** — tanish shablonlarini to'ldirish (eng katta xavf)
2. **K-1** — `/shadow` ni holat ko'rsatadigan qilish
3. **K-2** — relay qatlamida soya rejimini tekshirish
4. **K-4** — `/check` prefiks to'qnashuvi (bir qatorlik tuzatish)
5. **K-5** — adminbotni lichka bilan cheklash

**Birinchi hafta ichida:**

6. **M-1** — admin/tekshiruvchi xabarlarini `on_incoming` dan chiqarish
7. **M-2** — barcha partiyalarga natija yozish
8. **M-4** — `/stats` ko'rish cheklovi + eskirgan matn
9. **M-5** — "Sessiyalar" bo'limi (§4.3 talabi)
10. **M-6** — `permissions.py` bilan handler tekshiruvlarini birlashtirish

**Keyinroq:** M-3, M-7, P-1 … P-5.
