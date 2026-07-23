# Kupon Tekshirish va Nazorat Avtomatlashtirish Tizimi — MVP-1..MVP-6 (TO'LIQ)

TZ (`TZ_Data_Relay_System.md`) va `AI_AGENT_PROMPT.md` asosida qurilgan.
TZ 15-bo'limdagi barcha olti bosqich — **MVP-1** (Teleton + bot pool + asosiy
oqim), **MVP-2** (Adminbot), **MVP-3** (EXPIRED-qayta-urinish, shubhali-holat,
rasm-xato, bot timeout/retry), **MVP-4** (statistika, reconciliation,
audit_log, backup), **MVP-5** (real bot infratuzilmasi, ko'p-akkaunt,
Docker) va **MVP-6** (Web panel) — tayyor va sinovdan o'tgan.

## ⚠️ MVP-6: Telegram Login Widget — jonli sinalmagan (ataylab)

Panelga kirish usuli so'ralganda foydalanuvchi **Telegram Login Widget**ni
tanladi (login+parol tavsiya etilgan bo'lsa ham). Bu usul ishlashi uchun
Telegram bot @BotFather'da **real, ochiq HTTPS domenga** (`/setdomain`)
bog'langan bo'lishi shart — bu ishlab chiqish muhitida mavjud emas. Shuning
uchun:
- Hash-tekshiruv algoritmi (`panel_service/auth.py`) Telegram'ning rasmiy
  hujjatiga ("checking-authorization") asosan yozilgan va **to'liq unit-test
  qilingan** (sof funksiya, tarmoqqa bog'liq emas).
- Lekin **haqiqiy Telegram redirect bilan hech qachon sinalmagan**. Ishlab
  chiqarishga chiqarishdan oldin: (1) botga `/setdomain` orqali real domen
  sozlang, (2) `.env`da `ADMINBOT_USERNAME`ni to'ldiring, (3) `/login`
  sahifasida tugmani bosib to'liq oqimni qo'lda tekshiring.

## ⚠️ MVP-5: real botga ULANMAGAN (ataylab)

Foydalanuvchi MVP-5 boshlanishida real tekshiruv bot ma'lumotlarini
(username + namuna xabarlar) hali bermagani va jonli ulanishga alohida
ruxsat so'ralmagani sababli (AI_AGENT_PROMPT.md: "Real tekshiruv botlariga
ULANMA... alohida ruxsat bilan"), **faqat infratuzilma** qurildi:
- `RealVerificationBotAdapter` (`teleton_service/real_bot_adapter.py`) yozilgan,
  lekin **hech qanday haqiqiy botga qarshi sinalmagan**.
- Joriy runtime hamon **mock bot** bilan ishlaydi (`USE_REAL_VERIFICATION_BOTS=false`,
  standart qiymat).
- Real botga o'tish uchun: (1) `/botpatterns` orqali 4 ta bot-tanish shablonini
  kiriting, (2) `.env`da `USE_REAL_VERIFICATION_BOTS=true` qiling, (3) ishga
  tushirishdan oldin kamida bitta haqiqiy bot bilan qo'lda tekshiring.

## ⚠️ MVP-3 taxminlari (TZ aniq javob bermagan, foydalanuvchi savolga javob
bermay "boshla" degani uchun quyidagi **tavsiya etilgan variantlar** bilan
davom etildi — kerak bo'lsa keyin o'zgartirish oson):

1. **NEEDS_ADMIN'da mijozga matn** — TZ 7.2'da bu holat uchun alohida shablon
   yo'q. Mijozga oddiy `EXPIRED_RETRY` matni ko'rsatiladi (mijoz hech narsani
   sezmaydi, admin orqa fonda `/problems` orqali ko'rib chiqadi).
2. **Bloklash holatida case statusi** — TZ'da `BLOCKED` statusi yo'q (yangi
   status qo'shish taqiqlangan). Case `REJECTED`ga o'tadi, `user.is_blocked=True`
   bo'ladi, va bloklangan foydalanuvchidan kelgan **har qanday keyingi xabar**
   (nomer ham, kupon ham) butunlay jim e'tiborsiz qoldiriladi.
3. **5x EXPIRED limiti sanog'i** — birinchi EXPIRED ham hisobga kiradi
   (1-EXPIRED = 1-urinish); 5-marta ketma-ket EXPIRED bo'lsa `NEEDS_ADMIN`.
4. **EXPIRED holatida FARQLI nomer kelsa** — 2.3 (`DUPLICATE_ACTIVE`) kabi
   ishlov beriladi (botga yuborilmaydi, mijozdan aniqlashtiriladi + adminga
   xabar), chunki eski case hali "hal bo'lmagan" deb hisoblanadi.
5. **TIMEOUT'da mijozga matn** — tekshiruv bot javob bermay N marta urinib
   ham natija bermasa, TZ'da mijoz uchun shablon yo'q — hech qanday avtomatik
   javob yuborilmaydi (jim), admin `important=True` alert orqali xabardor
   qilinadi.
6. **5.2 (shubhali holat)da mijozga matn** — TZ mijoz uchun matn belgilamagan,
   shuning uchun case SUSPICIOUS_HOLD bo'lganda ham mijozga hech narsa
   yuborilmaydi (jim, tergovni oshkor qilmaslik uchun).

## ⚠️ MVP-4 taxminlari

7. **Restart reconciliation'da "ehtimol tasdiqlangan" belgisi** — TZ Q37
   "ba'zilarini 'ehtimol tasdiqlangan' deb belgilab, admin ko'rib chiqishi
   uchun yuborish" deydi, lekin bunday status yo'q va yangi status qo'shish
   taqiqlangan. Mavjud `NEEDS_ADMIN` qayta ishlatildi (aynan shu maqsad uchun:
   "noaniq holat — admin aralashuvi kerak"), alert matnida vaziyat ("restart
   paytida yarim qolgan, natija noaniq") aniq tushuntiriladi.
8. **Har admin/lichka bo'yicha statistika taqsimoti** — TZ 10-bo'lim so'raydi,
   lekin `Case.assigned_admin_id` hozircha hech qachon to'ldirilmaydi (bitta
   Teleton akkaunti bilan bu maydon mazmunsiz bo'lardi). `/stats` faqat
   umumiy (tizim bo'yicha) sonlarni ko'rsatadi; taqsimot ko'p akkaunt
   qo'shilganda (MVP-5) qo'shiladi.

## MVP-1 qamrovi (asosiy oqim)

- Mijoz lichkasidagi tabiiy suhbatdan telefon nomerini aniqlash (TZ 4, 4.1).
- Bot pool: 5–10 (mock) tekshiruv bot, LRU tanlash, bir vaqtda bitta case
  (TZ 3-bo'lim). Hamma bot band bo'lsa case navbatga tushadi, bot bo'shagach
  avtomatik tayinlanadi (Q45).
- Asosiy holat mashinasi: `NUMBER_RECEIVED → SENT_TO_BOT → AWAITING_COUPON →
  COUPON_SENT_TO_BOT → CONFIRMED/REJECTED/EXPIRED`.
- Mijoz 5 daqiqada kupon yubormasa seans to'xtaydi, bot bo'shaydi (TZ 2.2, Q48).
- Faol case bor holatda yangi nomer kelsa — botga yuborilmay admin ogohlantiriladi
  (TZ 2.3, Q49).
- Tasdiqlangan nomer qayta kelsa — botga yuborilmay avtomatik javob (TZ 2.4, Q50).
- Har bir kupon urinishi `coupon_attempts` jadvalida tarixiy saqlanadi (Q61).

## MVP-2 qamrovi (Adminbot)

`adminbot_service/` (aiogram 3.x) — TZ 9-bo'lim:

- **Bildirishnoma** — muhim hodisalar (CONFIRMED, REJECTED, CUSTOMER_TIMEOUT,
  TIMEOUT, DUPLICATE_ACTIVE, NEEDS_ADMIN, SUSPICIOUS_HOLD, navbat to'lganda)
  har doim adminlarga yuboriladi; EXPIRED kabi "muhim emas" hodisalar faqat
  **batafsil rejim** yoqilganda ko'rinadi — `/notify` bilan almashtiriladi
  (TZ 9.1).
- **`drop find <nomer>`** — nomer bo'yicha barcha case'lar, ularning holati va
  kupon urinishlari tarixini ko'rsatadi (Q61: kupon qiymatlari saqlangani
  uchun to'liq audit mumkin).
- **`/templates` / `/settemplate <KEY> <matn>`** — mijozga yuboriladigan 8 ta
  shablonni (TZ 7.2) ko'rish/o'zgartirish. Bazada saqlanadi, Teleton va
  Adminbot alohida jarayon bo'lsa ham o'zgarish darhol ta'sir qiladi (har
  chaqiriqda bazadan o'qiladi, kesh yo'q — TZ 13.1).
- **`/bots` / `/addbot <username> [format]`** — tekshiruv bot pool'ini
  ko'rish/kengaytirish (TZ 3.3, 9.5).
- **`/pending`** — hali bot topilmagan (navbatdagi) murojaatlar.
- **`/problems`** — admin e'tiborini talab qiladigan murojaatlar
  (`DUPLICATE_ACTIVE`, `NEEDS_ADMIN`, `SUSPICIOUS_HOLD`).
- **Inline tugmalar** — shubhali-holat xabarida `[Lichkaga o'tish]`,
  `[✅ Xavfsiz]`, `[🚫 Bloklash]` (TZ 9.3); rasm-xato xabarida
  `[Lichkaga o'tish]`.
- Faqat `admins` jadvalidagi Telegram ID-lar buyruq bera oladi (TZ 12.2);
  boshqalar "Sizda ruxsat yo'q" javobini oladi.

**Ataylab MVP-2'da yo'q** (keyingi bosqichlarga qoldirilgan): rol bo'linishi
(owner/rop/admin/kuzatuvchi, TZ 14-bo'lim — "keyin hal qilinadi"), bot-tanish
shablonlari (`bot_patterns`, faqat real botga ulanganda, MVP-5).

## MVP-3 qamrovi (EXPIRED-qayta-urinish, shubha, rasm-xato, timeout)

- **EXPIRED-qayta-urinish sikli (TZ 2.1, Q57/58/59)** — mijoz AYNAN O'SHA
  nomerni qayta yuborsa, bu YANGI case emas, eskisining qayta-urinishi
  (`Case.expired_attempts` +1). Bir xil (allaqachon EXPIRED bo'lgan) kupon
  qayta yuborilsa botga yuborilmay bloklanadi (Q58, `DUPLICATE_COUPON`
  shablon). 5-marta ketma-ket EXPIRED bo'lsa `NEEDS_ADMIN`ga o'tadi (Q59).
  Farqli nomer kelsa `DUPLICATE_ACTIVE` kabi ishlov beriladi (yuqoridagi
  taxmin #4).
- **Shubhali holat (TZ 5.2)** — bitta telefon nomeri BOSHQA Telegram
  akkauntidan ham kelgan bo'lsa, yangi case `SUSPICIOUS_HOLD`ga o'tadi (botga
  yuborilmaydi), `user.is_safe=False`, adminga inline tugmali ogohlantirish.
  Admin **Xavfsiz** bossa `user.is_safe=True` bo'ladi; Teleton'dagi fon
  vazifasi (`_suspicious_resume_watcher`, har `SUSPICIOUS_RESUME_POLL_SECONDS`
  soniyada tekshiradi) case'ni avtomatik dispatch qiladi — bu **Adminbot va
  Teleton alohida jarayon** bo'lgani uchun kerak (faqat Teleton mijoz bilan
  "admin nomidan" gaplasha oladi). Admin **Bloklash** bossa `is_blocked=True`
  + case `REJECTED`, kelajakdagi xabarlar jim qoldiriladi.
- **Rasm o'rniga kupon (TZ 5.1)** — `AWAITING_COUPON`da rasm/media kelsa,
  case holati o'zgarmaydi (timer ham to'xtamaydi), mijozga
  `IMAGE_INSTEAD_OF_TEXT` matni, adminga sender ma'lumoti bilan ogohlantirish.
- **Tekshiruv bot timeout/retry (TZ 12-bo'lim)** — bot javob bermasa
  (`BOT_RESPONSE_MAX_RETRIES`, standart 3) marta backoff bilan qayta
  urinadi, hammasi muvaffaqiyatsiz bo'lsa case `TIMEOUT`ga o'tadi, bot
  majburan bo'shatiladi (`force_release`), admin muhim alert oladi.

**Ataylab MVP-3'da yo'q:** umumiy shubha-aniqlash tizimi/rule-engine
(Q22 — "keyin ishlab chiqamiz"), rate-limit va avtomatik blacklist
(Q34/Q35 — ataylab MVP-dan tashqarida).

## MVP-4 qamrovi (statistika, reconciliation, audit, backup)

- **`/stats` (TZ 10-bo'lim)** — bugungi murojaatlar soni, barcha statuslar
  bo'yicha son (CONFIRMED/REJECTED/TIMEOUT va h.k.), joriy ochiq muammoli
  holatlar soni (`DUPLICATE_ACTIVE`+`NEEDS_ADMIN`+`SUSPICIOUS_HOLD`).
- **Restart reconciliation (TZ 12-bo'lim, Q37)** — Teleton ishga tushganda
  (`core/logic/reconciliation.py`) qayta ishga tushishdan oldin bot bilan
  muloqot o'rtasida (`SENT_TO_BOT`/`AWAITING_COUPON`/`COUPON_SENT_TO_BOT`)
  qolib ketgan case'lar topiladi — natija noaniq bo'lgani uchun `NEEDS_ADMIN`ga
  o'tkaziladi (yuqoridagi taxmin #7) va bot majburan bo'shatiladi. Hali botga
  yuborilmagan (`NUMBER_RECEIVED`, navbatdagi) case'lar esa — hech narsa
  yo'qolmagani uchun — xavfsiz qayta dispatch qilinadi.
- **`audit_log` (TZ 11.5, 12.2)** — holat o'zgartiruvchi admin harakatlari
  (`/addbot`, `/settemplate`, `/notify` toggle, Xavfsiz/Bloklash) kim-qachon-
  nima qildi tarzida yoziladi; `/audit` orqali so'nggi 20 tasi ko'riladi.
  O'qish-buyruqlari (`/bots`, `/templates`, `/pending`, `/problems`,
  `drop find`) audit talab qilmaydi — ular hech narsani o'zgartirmaydi.
- **Kunlik SQLite backup (TZ 13-bo'lim, Q60)** — Teleton fon vazifasi har
  `BACKUP_INTERVAL_SECONDS` (standart 24 soat) da `sqlite3`ning o'z
  `.backup()` APIsi orqali (fayl nusxalashdan farqli, yozish davom etsa ham
  izchil) `BACKUP_DIR`ga nusxa oladi, faqat oxirgi `BACKUP_RETENTION` tasini
  saqlaydi.
- **Strukturali log fayllar (TZ 12.1)** — har ikkala servis endi konsol +
  `LOG_DIR/{teleton,adminbot}.log` (rotatsiyalanuvchi, 5MB x 5 fayl) ga
  yozadi. Kritik alertlar (Adminbotga push) allaqachon MVP-1/2'dan beri
  ishlaydi (`case_manager._alert`, `AdminNotifier`).

**Ataylab MVP-4'da yo'q:** ko'p akkaunt bo'yicha statistika taqsimoti
(yuqoridagi taxmin #8, MVP-5'da haqiqiy ma'no kasb etadi).

## MVP-5 qamrovi (real bot infratuzilmasi, ko'p-akkaunt, Docker)

- **Bot-tanish shablonlari (TZ 7.1, 9.4 Q16)** — `bot_patterns` jadvali (4 ta
  majburiy kalit: `COUPON_REQUEST`/`CONFIRMED`/`EXPIRED`/`REJECTED`),
  `/botpatterns` (ko'rish) / `/setbotpattern <KEY> <matn>` (o'zgartirish).
  Bular **mijozga hech qachon yuborilmaydi** — faqat tekshiruv botning o'z
  javobini kichik/katta harf farqisiz substring orqali tanish uchun (TZ 3.2).
- **`VerificationBot` protokoli endi bot-xabardor** — arxitektura tuzatishi:
  avval `request_coupon`/`check_coupon` qaysi pool a'zosi (bot.username)
  orqali gaplashish kerakligini bilmas edi (mock bot uchun ahamiyatsiz, lekin
  real ko'p-bot rejimi uchun zarur). Endi ikkalasi ham `bot: Bot` obyektini
  qabul qiladi.
- **Bot javobi tanilmasa → `NEEDS_ADMIN`, TIMEOUT emas (TZ 8-bo'lim)** — agar
  real bot javob bersa-yu, matni bot_patterns'dan hech qaysiga mos kelmasa,
  bu "bot javob bermadi" emas, "javobni tushunmadik" degani — qayta urinish
  foydasiz, darhol admin ko'rib chiqishi kerak (`UnrecognizedBotResponseError`).
- **`RealVerificationBotAdapter`** (`teleton_service/real_bot_adapter.py`) —
  Telethon'ning `client.conversation()` so'rov-javob mexanizmi orqali (TZ 3.2:
  har bot bir vaqtda bitta case yuritgani uchun keyingi xabar aniq shu
  so'rovning javobi, maxsus marker kerak emas); `bot.needs_start_greeting`
  bo'lsa birinchi ishlatishda `/start` yuboradi (Q54). **Yuqoridagi ogohlantirish
  qarang — hali jonli sinalmagan.**
- **Ko'p-akkaunt tuzilmaviy tayyorligi (Q55)** — `Bot.owner_admin_id`: `None`
  bo'lsa umumiy (bitta akkaunt) pool, aks holda faqat shu admin'ning Teleton
  sessiyasi undan foydalana oladi ("har admin+bot mustaqil slot" — TZ'ning
  xavfsiz standart javobi). `BotPoolManager`/`CaseManager` ikkalasi ham
  `owner_admin_id` parametrini qabul qiladi. **Faqat ma'lumotlar modeli va
  pool-filtrlash tayyor** — bir nechta HAQIQIY Telethon sessiyasini bir vaqtda
  ishga tushirish sinalmagan (buning uchun 2-chi haqiqiy Telegram akkaunt kerak).
- **Docker Compose** — `Dockerfile` + `docker-compose.yml` (ikkala servis bitta
  image, umumiy volume). **Bu muhitda Docker o'rnatilmagani uchun
  qurilmagan/sinovdan o'tkazilmagan** — standart konfiguratsiya, ishlatishdan
  oldin o'zingiz `docker compose up --build` bilan tekshiring.

**Ataylab MVP-5'da yo'q:** haqiqiy botga jonli ulanish va sinov (foydalanuvchi
hali ruxsat bermagan), bir nechta HAQIQIY Telethon sessiyasini parallel ishga
tushirish (ikkinchi real akkaunt yo'q).

## MVP-6 qamrovi (Web panel — TZ 13-bo'lim, 11.6)

`panel_service/` (FastAPI, faqat O'QISH uchun — holat o'zgartiruvchi amallar
Adminbot orqali qoladi, bu yerda takrorlanmaydi):

- **Kirish** — Telegram Login Widget (yuqoridagi ogohlantirishga qarang).
  Faqat `admins` jadvalidagi Telegram ID-lar kira oladi (TZ 12.2) — sessiya
  imzolangan cookie orqali (`itsdangerous`, `PANEL_SESSION_SECRET`).
- **Dashboard (`/`)** — statistika (TZ 10-bo'lim, Adminbot `/stats` bilan bir
  xil `core.logic.stats`).
- **Murojaatlar (`/cases`)** — nomer/status/sana bo'yicha qidiruv-filtr
  (TZ 11.6), har bir case tafsiloti (`/cases/{id}`) — kupon urinishlari
  tarixi (Q61).
- **Mijozlar (`/customers`)** — CRM ko'rinishi: qidiruv (nomer/username/ism),
  xavfsiz/shubhali/bloklangan holati, har mijozning murojaatlar tarixi
  (`/customers/{id}`).
- **Audit (`/audit`)** — admin harakatlari tarixi (Adminbot `/audit` bilan
  bir xil ma'lumot manbai).

**Ataylab MVP-6'da yo'q:** Q51'dagi rol-asoslangan ko'rish cheklovi (rollar
hali TZ 14-bo'lim bo'yicha "keyin hal qilinadi"; hozircha har admin panelda
ham hammasini ko'radi — Adminbot bilan bir xil qoida), har admin/lichka
bo'yicha statistika taqsimoti (yuqoridagi taxmin #8 bilan bir xil sabab),
panel orqali yozish/tahrirlash (shablon, bot qo'shish va h.k. — ataylab
faqat Adminbotda, ikki joyda bir xil narsani boshqarish xatoga moyil).

## Loyihadagi eski fayl haqida eslatma

`data_relay_userbot.py` — TZ yozilishidan oldingi, sodda (bot pool'siz,
bitta statik `RELAY_TARGET` botga uzatuvchi) prototip. Yangi arxitektura
(`core/`, `teleton_service/`, `adminbot_service/`) uni almashtiradi. Fayl
o'chirilmadi — kerak bo'lsa qo'lda solishtirib ko'rish uchun qoldirildi.

## Fayl tuzilmasi

```
core/
  config.py             — .env sozlamalari
  enums.py              — CaseStatus, ACTIVE_STATUSES, PENDING_STATUSES (TZ 6-bo'lim)
  models.py             — SQLAlchemy ORM (users, cases, coupon_attempts, bots,
                           admins, templates, settings, audit_log, bot_patterns)
  db.py                 — async engine/session + sqlite_file_path()
  texts.py              — shablonlarning BOSHLANG'ICH qiymatlari (TZ 7.2)
  logic/
    phone.py             — O'zbekiston nomer aniqlash/normalizatsiya (TZ 4.1)
    bot_pool.py           — bot pool/navbat menejeri + owner_admin_id scoping (TZ 3-bo'lim, Q55)
    case_manager.py        — asosiy holat mashinasi (TZ 2, 5, 6, 8, 9, 12-bo'lim)
    templates.py            — mijozga yuboriladigan shablonlar (TZ 7.2)
    bot_patterns.py           — bot-TANISH shablonlari (TZ 7.1, 9.4 Q16)
    admins.py                  — admin ro'yxati va kirish nazorati (TZ 12.2)
    settings_store.py           — umumiy kalit-qiymat sozlamalar (bildirishnoma rejimi)
    notifier.py                  — AdminNotifier: oddiy/rasm-xato/shubha alertlar (TZ 9.1, 5.1, 5.2)
    audit.py                      — admin harakatlari tarixi (TZ 11.5, 12.2)
    stats.py                       — statistika hisoblash (TZ 10-bo'lim)
    reconciliation.py               — restart reconciliation (TZ 12-bo'lim, Q37)
    backup.py                       — kunlik SQLite backup (TZ 13-bo'lim, Q60)
    logging_setup.py                 — konsol + fayl logging (TZ 12.1)
teleton_service/
  mock_bot.py             — soxta tekshiruv bot + timeout simulyatsiyasi (TZ 10.1, 12)
  real_bot_adapter.py      — real botga Telethon conversation orqali ulanuvchi
                             adapter (TZ 3.2, 7.1) — HALI JONLI SINALMAGAN
  relay.py                — Telethon klient, rasm/media, shubha-resume poller,
                             reconciliation, backup fon vazifasi, real-bot gate
adminbot_service/
  bot.py                  — aiogram Adminbot: barcha buyruqlar + safe/block callback'lar
panel_service/
  app.py                  — FastAPI: login/auth/dashboard/cases/customers/audit
  auth.py                  — Telegram Login Widget hash-tekshiruvi — JONLI SINALMAGAN
  templates/               — Jinja2 HTML (base, login, dashboard, cases, customers, audit)
core/logic/case_search.py, customers.py — panel uchun qidiruv/filtr (TZ 11.6)
tests/                    — pytest (bot pool, holat mashinasi, nomer validatsiyasi,
                             admin/shablon/sozlama, MVP-3, MVP-4, MVP-5, MVP-6 xususiyatlari)
Dockerfile, docker-compose.yml — MVP-5/6 (qurilmagan/sinovdan o'tkazilmagan, quyida)
```

## O'rnatish

```bash
pip install -r requirements.txt
cp .env.example .env
```

`.env` faylida to'ldiring:
- `API_ID` / `API_HASH` — https://my.telegram.org (Teleton uchun).
- `ADMINBOT_TOKEN` — @BotFather'dan yangi bot yaratib oling (Adminbot uchun).
- `ADMIN_TG_IDS` — o'zingizning Telegram ID-ingiz (@userinfobot orqali bilib
  oling). **Bo'sh qoldirmang** — aks holda Adminbotga hech kim buyruq bera
  olmaydi (TZ 12.2).
- `BOT_RESPONSE_MAX_RETRIES` / `BOT_RESPONSE_BACKOFF_SECONDS` — tekshiruv bot
  javob bermasa necha marta va qancha kutib qayta urinish (TZ 12-bo'lim).
- `SUSPICIOUS_RESUME_POLL_SECONDS` — "Xavfsiz" deb belgilangan case necha
  soniyada dispatch qilinishi (TZ 5.2).
- `BACKUP_DIR` / `BACKUP_INTERVAL_SECONDS` / `BACKUP_RETENTION` — kunlik
  SQLite backup sozlamalari (TZ 13-bo'lim, Q60).
- `LOG_DIR` — strukturali log fayllar papkasi (TZ 12.1).
- `USE_REAL_VERIFICATION_BOTS` — **standart `false`** (mock bot bilan davom
  etadi). `true` qilishdan oldin `/botpatterns` orqali 4 ta shablonni to'liq
  kiriting (TZ 9.4, Q16) — aks holda Teleton STOP bo'ladi. ⚠️ Bu adapter hali
  jonli sinalmagan (yuqoridagi MVP-5 ogohlantirishga qarang).
- `ADMINBOT_USERNAME` — Adminbot bilan BIR XIL bot username'i (Telegram Login
  Widget shu bot nomidan login qiladi). `PANEL_HOST`/`PANEL_PORT` — web panel
  qaysi manzilda ishga tushishi. `PANEL_SESSION_SECRET` — sozlanmasa har
  ishga tushirishda tasodifiy (seanslar restart'da bekor bo'ladi).

Birinchi marta shaxsiy akkauntga ulanish uchun (agar `my_account.session`
hali yo'q bo'lsa):

```bash
python login.py
```

## Ishga tushirish

Ikkala jarayon alohida-alohida, parallel ishga tushiriladi (TZ 13.1
mikroservis mantig'i — hozircha bitta repo, bitta SQLite baza):

```bash
python -m teleton_service.relay
python -m adminbot_service.bot
uvicorn panel_service.app:app --host 0.0.0.0 --port 8000   # Web panel (MVP-6)
```

Teleton haqiqiy Telethon orqali sizning shaxsiy akkauntingiz lichkalarini
kuzata boshlaydi, lekin tekshiruv bot sifatida **mock bot**dan foydalanadi
(real tekshiruv botlarga ulanish yo'q — TZ va AI_AGENT_PROMPT talabi).
Adminbot esa `.env`dagi `ADMIN_TG_IDS`da ko'rsatilgan Telegram ID-lardan
buyruqlarni qabul qiladi. Teleton ishga tushganda avtomatik restart
reconciliation (Q37) o'tkazadi va kunlik backup fon vazifasini boshlaydi.

Mock bot standart test kuponlari (`teleton_service/mock_bot.py`):

| Kupon    | Natija     |
|----------|------------|
| `111111` | CONFIRMED  |
| `222222` | EXPIRED    |
| `333333` | REJECTED   |
| boshqa har qanday 6 xonali | REJECTED ("topilmadi") |

## Adminbot buyruqlari

| Buyruq | Vazifa |
|---|---|
| `drop find <nomer>` | Nomer bo'yicha holat + kupon tarixi |
| `/bots` | Tekshiruv botlari ro'yxati va holati |
| `/addbot <username> [format] [start]` | Yangi tekshiruv bot qo'shish (`start` — avval `/start` yuborilsin, Q54) |
| `/templates` | Mijozga yuboriladigan shablonlarni ko'rish |
| `/settemplate <KEY> <matn>` | Shablonni o'zgartirish |
| `/botpatterns` | Bot-TANISH shablonlarini ko'rish (mijozga yuborilmaydi, TZ 7.1) |
| `/setbotpattern <KEY> <matn>` | Bot-tanish shablonini o'zgartirish |
| `/notify` | Bildirishnoma rejimini ko'rish/o'zgartirish (oddiy/batafsil) |
| `/pending` | Navbatda turgan murojaatlar |
| `/problems` | Admin e'tiborini talab qiladigan murojaatlar |
| `/stats` | Statistika (TZ 10-bo'lim) |
| `/audit` | So'nggi 20 ta admin harakati |
| *(inline)* ✅ Xavfsiz / 🚫 Bloklash | Shubhali-holat xabarida — TZ 5.2, 9.3 |

## Web panel sahifalari (MVP-6, faqat o'qish)

| Sahifa | Vazifa |
|---|---|
| `/login` | Telegram Login Widget (⚠️ jonli sinalmagan) |
| `/` | Dashboard — statistika |
| `/cases` | Murojaatlar qidiruv/filtr (nomer, status, sana) |
| `/cases/{id}` | Case tafsiloti + kupon urinishlari tarixi |
| `/customers` | Mijozlar ro'yxati (CRM), qidiruv |
| `/customers/{id}` | Mijoz tafsiloti + murojaatlar tarixi |
| `/audit` | Admin harakatlari tarixi |
| `/logout` | Seansni tugatish |

## Docker (MVP-5/6 — qurilmagan/sinovdan o'tkazilmagan)

```bash
cp .env.example .env   # to'ldiring
docker compose up --build
```

Birinchi marta Telethon akkauntga ulanish (interaktiv):

```bash
docker compose run --rm -it teleton python login.py
```

`Dockerfile`/`docker-compose.yml` bitta image'dan uchta servisni (`teleton`,
`adminbot`, `panel`) alohida jarayon sifatida ishga tushiradi, umumiy `data`
volume orqali SQLite baza/log/backup fayllarini baham ko'radi. Panel
`http://localhost:8000`da ochiladi. **Bu ishlab chiqish muhitida Docker
o'rnatilmagani uchun `docker compose up --build` bilan o'zingiz tekshirib
ko'ring** — standart, keng tarqalgan konfiguratsiya, lekin tasdiqlanmagan.

## Sinash

```bash
pytest -v
```

76 ta test:
- Bot pool (band/bo'sh, LRU, navbat, `/addbot`/`/bots`, owner_admin_id scoping).
- Holat mashinasi: tasdiq, rad, EXPIRED-qayta-urinish (bir xil nomer → shu
  case, farqli nomer → DUPLICATE_ACTIVE, 5x → NEEDS_ADMIN), dublikat-kupon
  bloklanishi (Q58), dublikat-faol case, tasdiqlangan-qayta-kelgan nomer,
  navbatdagi case avtomatik tayinlanishi, mijoz timeout.
- Nomer validatsiyasi.
- MVP-2: admin ro'yxati, bildirishnoma rejimi, shablon o'qish/yozish +
  case_manager integratsiyasi, alert severity klassifikatsiyasi.
- MVP-3: shubhali-holat aniqlash + Xavfsiz'dan keyin qayta ishga tushirish,
  bloklangan foydalanuvchi jim e'tiborsiz qoldirilishi, rasm-o'rniga-kupon,
  tekshiruv bot timeout/retry.
- MVP-4: audit log yozish/o'qish, statistika hisoblash (bugungi/status/
  muammoli), restart reconciliation (yarim qolgan → NEEDS_ADMIN + bot
  bo'shaydi; navbatdagi → xavfsiz qayta dispatch — haqiqiy "yangi jarayon"
  simulyatsiyasi bilan sinaldi), backup yaratish + restorable ekanligi +
  retention pruning.
- MVP-5: bot-tanish shablon gate/matching, bot-xabardor protokol (to'g'ri
  `bot.username` uzatilishi), tanilmagan bot javobi → NEEDS_ADMIN (qayta
  urinishsiz), ko'p-akkaunt pool scoping, `RealVerificationBotAdapter`ning
  klassifikatsiya mantig'i (soxta Telethon conversation bilan, tarmoqsiz).
- MVP-6: Telegram Login Widget hash-tekshiruvi (to'g'ri/soxtalashtirilgan/
  eskirgan/noto'g'ri bot token — barchasi tarmoqsiz, deterministik), murojaat
  qidiruv-filtr (nomer/status/sana), mijozlar qidiruvi+tarixi, FastAPI
  route'lari (autentifikatsiyasiz redirect, izolyatsiyalangan test bazasi
  bilan autentifikatsiyalangan sahifalar, 404 ishlovi).

Real Telegram'siz to'liq end-to-end stsenariyni tekshirish uchun uch usul
qo'llanildi:
1. `core.logic.case_manager.CaseManager`ni mock bot bilan to'g'ridan-to'g'ri
   chaqiruvchi qo'lda yozilgan skript.
2. `adminbot_service.bot` handler'larini soxta (fake) `Message`/`CallbackQuery`
   obyektlari bilan izolyatsiyalangan vaqtinchalik SQLite bazaga qarshi
   ishga tushiruvchi smoke-test — barcha MVP-2/3/4/5 buyruqlari, callback'lar
   (`safe:`, `block:`, `notify:`), `/stats`, `/audit`, `/botpatterns`,
   `/addbot ... start`, reconciliation va backup tekshirildi.
3. `panel_service.app`ni FastAPI `TestClient` + izolyatsiyalangan bazaga
   ulangan `dependency_overrides` orqali sinash — barcha sahifalar (dashboard,
   cases, customers, audit) haqiqiy ma'lumot bilan 200 qaytarishi tekshirildi.

## TZ 15-bo'lim — barcha bosqichlar yakunlandi

MVP-1 dan MVP-6 gacha qurilgan va sinovdan o'tgan. Qolgan ishlar — yuqorida
sanab o'tilgan, ataylab jonli sinalmagan/qoldirilgan qismlar (real bot
ulanishi, ko'p-akkaunt jonli ishga tushirish, Telegram Login Widget'ning real
domen bilan sinovi, Docker'ning haqiqiy build/run tekshiruvi, rol tizimi) —
ularning barchasi yuqorida aniq ogohlantirilgan va foydalanuvchi tomonidan
real ma'lumot/ruxsat berilganda davom ettirilishi mumkin.
