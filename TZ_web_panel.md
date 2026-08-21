# TZ — Web Panel (Admin Boshqaruv Paneli)

> **Holat:** loyiha (draft). Suhbat asosida yozildi, ba'zi punktlar hali
> aniqlashtirilishi kerak — 10-bo'limga qarang.
> **Bog'liq hujjatlar:** `TZ_v2_Qolda_Admin_Oqimi.md` (asosiy oqim, rol
> tizimi, statistika manbai), `README_v2.md`.

---

## 1. Maqsad va sabab

Hozir rol/ruxsat/eslatma/statistika boshqaruvi **faqat Telegram bot
buyruqlari** orqali (`adminbot_service/bot.py`) amalga oshadi. Amaliyotda
muammo chiqdi:

> Kim tekshiruvchi, kim admin, kim kuzatuvchi ekanini rol orqali ajratib
> bo'lsa ham — ularga **rolidan tashqari qo'shimcha huquq** berib bo'lmayapti,
> eslatmalarni yoqib-o'chirib bo'lmayapti, statistikani botda kuzatish
> noqulay.

Web panel (`panel_service/`) hozircha **faqat o'qish uchun** qurilgan
(`panel_service/app.py:1-9` — dashboard, audit, case va mijozlar ro'yxati).
Bu TZ shu panelni **to'liq boshqaruv paneliga** aylantirishni maqsad qiladi:
rol, individual ruxsat, eslatma sozlamalari va statistika — hammasi
paneldan boshqariladi.

---

## 2. Hozirgi holat (kod tahlili xulosasi)

| Mavzu | Hozirgi holat |
|---|---|
| Rol tizimi | `AdminRole`: OWNER / ROP / DASTURCHI / ADMIN / KUZATUVCHI (`core/models.py`). Ruxsatlar yagona markazda: `core/logic/permissions.py` (`COMMANDS`, `CALLBACKS` jadvallari + `RolePermission` middleware) |
| Rol o'zgartirish | `/setrole` — faqat OWNER (`adminbot_service/bot.py`) |
| Faol/nofaol | `/setactive` — faqat OWNER |
| Qo'shimcha ruxsat | `Admin.can_view_all_stats` bor, lekin **hech qanday setter yo'q** — bot orqali ham, panel orqali ham o'zgartirib bo'lmaydi |
| Eslatmalar | Faqat **global** on/off (`/notify`, `NOTIFY_VERBOSE`) — barcha adminlarga bir xil, individual sozlash yo'q |
| Statistika | `core/logic/v2_stats.py::gather_v2_stats` — admin kesimida boy, tayyor funksiya bor (kunlik/haftalik/oylik, konversiya %, javob vaqti). Panel hozir eski `stats.py::gather_stats`ni ishlatadi |
| Panel | `panel_service/app.py` — faqat O'QISH: login, dashboard, audit, case/mijoz ro'yxati. Hech qanday POST/o'zgartiruvchi endpoint yo'q |
| Auth | Telegram Login Widget (`auth.py`) — **hali jonli sinalmagan** |

**Xulosa:** biznes-mantiq (`core/logic/*`) allaqachon aiogram'dan mustaqil
sof funksiyalar sifatida yozilgan — bu web panel uchun katta afzallik, chunki
bot va panel bitta manbadan ishlashi mumkin, mantiq ikki marta yozilmaydi.

---

## 3. Rol va faollik boshqaruvi (paneldan)

Mavjud `core/logic/admins.py::set_admin_role` va `is_last_active_owner`
mantig'ini paneldagi yangi write-endpoint to'g'ridan-to'g'ri chaqiradi.

- Sahifa: **Adminlar** — ro'yxat (ism, username, rol, faollik, oxirgi
  faollik vaqti).
- Rol o'zgartirish — dropdown, faqat OWNER'ga ko'rinadi/ishlaydi.
- Faol/nofaol qilish — toggle, faqat OWNER'ga. Nofaol qilinganda ochiq
  case'lar muzlatilishi haqida ogohlantirish ko'rsatiladi (mavjud bot
  xulq-atvori bilan bir xil, TZ v2 §4.2b).
- OWNER oxirgisi bo'lsa — o'zgartirish oldidan aniq ogohlantirish
  (`is_last_active_owner` mantig'i takrorlanadi).

---

## 4. Individual ruxsat overraydi ("ovoz")

**Qaror (suhbatda aniqlashtirildi):** "ovoz" — rolga bog'liq bo'lmagan,
**alohida-alohida beriladigan qo'shimcha huquq**. Masalan KUZATUVCHI
(odatda faqat ko'radi) yoki hatto OWNER'ga ham, rolini o'zgartirmasdan,
bitta aniq amal huquqi qo'shib qo'yish mumkin bo'lishi kerak.

**Shakl:** mavjud buyruqlar/amallar ro'yxatidan tanlab beriladi — erkin
matn/teg emas, `core/logic/permissions.py`dagi `COMMANDS`/`CALLBACKS`
registridagi kalitlar bilan bir xil ro'yxatdan.

**Yangi jadval — `admin_permission_grants`:**

```
admin_permission_grants
  id · admin_id → admins.id
  permission_key      (COMMANDS/CALLBACKS registridagi kalit, masalan "vstats_all")
  granted_by_admin_id → admins.id
  granted_at
```

**Tekshiruv mantig'i:** hozirgi rol-asosli tekshiruvga ("bu buyruq shu
rollarga ochiq") qo'shimcha shart qo'shiladi: "**yoki** shu adminga
alohida grant qilingan bo'lsa ham ruxsat ber". Bu tekshiruv **bitta joyda**
qoladi (`core/logic/permissions.py` + `RolePermission` middleware) va
**ikkalasida ham** — botda ham, panelda ham — ishlaydi. Ikki xil ruxsat
manbai paydo bo'lmasligi muhim.

**Panel UI:** Adminlar sahifasidagi har bir qatorda "+ ruxsat qo'shish"
tugmasi — ro'yxatdan tanlanadi, qo'shilgan ruxsatlar chip/teg ko'rinishida
ko'rsatiladi, bekor qilish tugmasi bilan.

---

## 5. Eslatma sozlamalari (granular, faqat OWNER/ROP)

**Qaror:** eslatmalar **har bir tur bo'yicha alohida** yoqiladi/o'chiriladi
(bitta umumiy tugma emas). Sozlashni **faqat OWNER/ROP** qiladi — oddiy
admin o'zi o'zgartira olmaydi (markazlashgan boshqaruv).

Turlar mavjud `ScheduledJob.JobKind` va `notifier.py` funksiyalariga mos
keladi:

| Tur | Manba |
|---|---|
| `REMIND_NO_SCREENSHOT` | rasm tashlanmadi eslatmasi |
| `STALLED_ALERT` | tekshiruvchi javob bermadi |
| `DAILY_REPORT` | kunlik hisobot |
| `NOTIFY_FAILED` | tekshiruv muvaffaqiyatsiz/aniqlanmadi |
| `IMAGE_WARNING` | shubhali rasm ogohlantirishi (`notifier.py::send_image_warning`) |
| `SUSPICIOUS_ALERT` | shubhali holat (`notifier.py::send_suspicious_alert`) |

**Yangi jadval — `admin_notification_preferences`:**

```
admin_notification_preferences
  id · admin_id → admins.id
  notification_type   (yuqoridagi ro'yxatdan)
  enabled (bool, standart = true)
  updated_by_admin_id → admins.id
  updated_at
```

**Panel UI:** **Eslatmalar** sahifasi — matritsa ko'rinishi: qatorlar
= adminlar, ustunlar = eslatma turlari, har katakda checkbox.

**Kod tegishi:** `core/logic/notifier.py::_broadcast` (va navbatdosh
funksiyalar) `list_admin_tg_ids`dan olingan ro'yxatni shu jadval bo'yicha
filtrlaydi — o'chirilgan turdagi eslatma o'sha adminga yuborilmaydi.

---

## 6. Statistika sahifasi

- Manba: `core/logic/v2_stats.py::gather_v2_stats` / `gather_with_comparison`
  / `leaderboard` — mavjud, to'g'ridan-to'g'ri ulanadi (eski `stats.py`
  o'rniga).
- Davr filtri: Bugun / Kecha / Hafta / Oy / Hammasi (mavjud
  `_VSTATS_PERIODS` mantig'i bilan bir xil).
- Ko'rish cheklovi — bot bilan **bir xil qoida**: OWNER/ROP yoki
  `can_view_all_stats=True` bo'lsa hammasini, aks holda faqat o'zinikini
  (`_vstats_unrestricted` mantig'i qayta ishlatiladi).
- Jadval + reyting (leaderboard), kelajakda oddiy grafik (masalan
  konversiya % ustunli diagramma) qo'shilishi mumkin — bu bosqichda shart
  emas.

---

## 7. Audit

Panel orqali qilingan **har bir o'zgartiruvchi amal** (rol, faollik,
ruxsat grant/revoke, eslatma toggle) mavjud `AuditLog` jadvaliga yoziladi
— bot buyruqlaridagi bilan **bitta umumiy jurnal**da. Panelning **Audit**
sahifasi bularni ham ko'rsatadi (kim, qachon, nima, kim uchun).

---

## 8. Arxitektura prinsipi

Yangi write-endpoint'lar (`panel_service/app.py`ga qo'shiladigan POST
route'lar) **to'g'ridan-to'g'ri** `core/logic/admins.py`,
`core/logic/permissions.py`, `core/logic/settings_store.py` (va yangi
qo'shiladigan funksiyalar) ni chaqiradi. `adminbot_service/bot.py`dagi
mantiq **takrorlanmaydi** — ikkalasi (bot va panel) bitta biznes-qatlamdan
ishlaydi.

---

## 9. Xavfsizlik / Auth

Panel endi faqat o'qish emas, **yozish** ham qila oladigan bo'lgani uchun
autentifikatsiya avval mustahkamlanishi shart:

- Hozirgi Telegram Login Widget (`auth.py`) **hali jonli sinalmagan** —
  birinchi bosqichda (P-1) bu tekshirilib, kerak bo'lsa tuzatiladi.
- Panel'dagi har bir sahifa/tugma rolga qarab ko'rsatiladi/yashiriladi —
  bot bilan **bir xil** `permissions.py` jadvalidan.
- Har bir yozuvchi amal serverda **qayta tekshiriladi** (frontend
  yashirish yetarli emas) — xuddi botdagi `RolePermission` middleware
  kabi.

---

## 10. Ma'lumotlar modeli — yangi jadvallar (yig'ma)

```
admin_permission_grants
  id · admin_id → admins.id · permission_key
  granted_by_admin_id → admins.id · granted_at

admin_notification_preferences
  id · admin_id → admins.id
  notification_type · enabled (bool, default true)
  updated_by_admin_id → admins.id · updated_at
```

Ikkalasi ham alembic migratsiya bilan qo'shiladi (mavjud
`alembic/versions/` namunalariga qarab).

---

## 11. Bosqichlar

| Bosqich | Mazmuni |
|---|---|
| **P-1 · Poydevor** | Auth mustahkamlash/sinov (Telegram Login Widget), panel route'larida rolga asoslangan ruxsat tekshiruvi (`permissions.py` bilan bir xil manba) |
| **P-2 · Adminlar boshqaruvi** | Rol, faol/nofaol, individual ruxsat overraydi (`admin_permission_grants` + UI) |
| **P-3 · Eslatma sozlamalari** | `admin_notification_preferences` jadvali + matritsa UI + `notifier.py` filtri |
| **P-4 · Statistika** | `v2_stats.py` ulash, davr filtri, reyting |
| **P-5 · Mustahkamlash** | Barcha write amallar `AuditLog`ga yoziladi, testlar |

---

## 12. Ochiq savollar

### ✅ Hal qilinganlar

| Savol | Qaror |
|---|---|
| "Ovoz" nima anglatadi | Rolga bog'liq bo'lmagan, alohida beriladigan qo'shimcha huquq (§4) |
| Ruxsat overraydi shakli | Mavjud buyruqlar ro'yxatidan tanlash, erkin matn emas (§4) |
| Eslatma granularligi | Har bir tur alohida yoqiladi/o'chiriladi (§5) |
| Eslatmani kim sozlaydi | Faqat OWNER/ROP — admin o'zi emas (§5) |
| Panel ko'lami | To'liq boshqaruv (o'qish + yozish), bot buyruqlariga qo'shimcha (§1) |

### ⏳ Ochiq qolganlar

1. Panel to'liq ishga tushgach, bot buyruqlari (`/setrole`, `/notify`
   va h.k.) **olib tashlanadimi** yoki ikkalasi parallel ishlayveradimi?
2. `admin_permission_grants`da qaysi aniq `permission_key`larni
   berish mumkin bo'lishi kerak — barcha `COMMANDS`/`CALLBACKS` ro'yxatimi,
   yoki faqat bir qismi (masalan `_TECH` toifasidagi texnik amallar
   bundan chetda qolishi kerakmi)?
3. Statistikaga grafik/vizual qo'shish shu bosqichda kerakmi, yoki
   jadval yetarlimi?
