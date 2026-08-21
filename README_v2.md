# v2 — Qo'lda Admin Oqimi: ishga tushirish yo'riqnomasi

> TZ: `TZ_v2_Qolda_Admin_Oqimi.md`. Eski (v1, avtomatik bot-pool) tizim
> haqida `README.md` — u kod bazasida qoladi, lekin ULANMAGAN (TZ v2 §12).
> v2 kirish nuqtasi: `python -m teleton_service.manual_relay`.

## Tizim nima qiladi (bir jumlada)

Adminlar mijozlar bilan O'Z shaxsiy akkauntlarida odatdagidek ishlayveradi;
tizim (har akkauntga ulangan Telethon) nomerlarni qayd etadi, admin tashlagan
rasmlarni nazorat guruhiga caption bilan forward qiladi, 1.5 soatdan keyin
(yoki `/check` bilan darhol) nomerni tekshiruvchi lichkadan so'raydi, javobni
shablonlar orqali tanib natijani tarqatadi (mijoz / guruh reaksiyasi /
adminbot) va hammasini statistikaga yozadi.

## O'rnatish (VDS, Dockersiz — TZ v2 §13)

```bash
# 1. Kod va muhit
cd /opt && git clone <repo> chatbot2 && cd chatbot2
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# 2. Sozlash
cp .env.example .env   # API_ID, API_HASH, ADMINBOT_TOKEN, ADMIN_TG_IDS to'ldiring

# 3. Baza migratsiyasi
venv/bin/python -m alembic upgrade head

# 4. Admin akkauntlarini ulash (har admin uchun bir marta, interaktiv)
venv/bin/python -m scripts.add_admin_session

# 5. systemd xizmatlari
cp deploy/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now teleton-v2 adminbot
```

Xavfsizlik (TZ v2 §13.4): `sessions/` papkasi — adminlarning akkauntlariga
TO'LIQ kirish. `chmod 700 sessions`, SSH faqat kalit bilan, backupga qo'shmang.

## Birinchi sozlash (adminbot orqali, tartib muhim)

| # | Buyruq | Nima qiladi |
|---|---|---|
| 1 | Botni nazorat guruhiga qo'shing, guruh ichida `/setgroup` | Rasm partiyalari shu guruhga tushadi. Admin akkauntlari ham guruhga a'zo bo'lsin! |
| 2 | `/setchecker <username yoki id>` | Tekshiruvchi lichka. Tekshiruvchi har bir admin akkauntidan xabar qabul qila olishi kerak |
| 3 | `/addcheckpattern OTDI bor` (va h.k.) | Uch kategoriya (OTDI/OTMADI/XATO) har birida kamida bittadan — bo'lmasa dvigatel ishga tushmaydi |
| 4 | `/testcheck <haqiqiy javob>` | Tanishni sinash |
| 5 | *(soya rejimi standart YOQILGAN)* | 1–2 kun kuzating: `/unrecognized` jurnalidan shablonlarni tugma bilan to'ldiring |
| 6 | `/shadow off` | Jonli rejimga o'tish — endi natijalar mijozlarga boradi. **Argumentsiz `/shadow` faqat holatni ko'rsatadi**, hech narsani o'zgartirmaydi (avval u almashtirib yuborardi — jonli sinovda soya rejimi tasodifan 2 marta o'chib ketgan edi) |

## Kundalik foydalanish

- **Admin:** mijoz nomer yozadi → rasm tashlaydi → bo'ldi. Xohlasa nomerli
  xabarga reply qilib `/check` (xabar o'zi o'chadi). Qolganini tizim qiladi.
- **`/vstats`** — statistika (Bugun/Hafta/Oy). Oddiy admin faqat o'zinikini
  ko'radi.
- **21:00** — guruhga kunlik hisobot, superadminga batafsil nusxa.
- **`/setactive <tg_id> off`** — admin ketsa: case'lari muzlatiladi, ro'yxat
  superadminga chiqadi. `on` — qaytganda.
- **Sessiya uzilsa** (admin "Terminate all sessions" bossa) — superadminga
  darhol alert; `scripts/add_admin_session.py` bilan qayta login qilinadi.

## Yangi admin qo'shish

```bash
venv/bin/python -m scripts.add_admin_session   # telefon -> kod -> (2FA)
systemctl restart teleton-v2                    # yangi klient ulanadi
```

## Muhim texnik eslatmalar

- **Reaksiya emojilari:** Telegram standart to'plamida ⚠️ va ⏳ yo'q — tizim
  rad etilsa 🤔 (noaniq) va 😴 (javobsiz) bilan qo'yadi. 👍/👎 odatdagidek.
- **Taymerlar bazada** (`scheduled_jobs`) — restart hech narsani yo'qotmaydi.
- **Navbat:** tezlik cheklovi yo'q — navbatdagi so'rovlar 20 soniya ichida
  hammasi tekshiruvchiga ketadi. Ko'p so'rov ochiq bo'lganda tekshiruvchi
  reply yoki oxirgi-4-raqam bilan javob bergani ma'qul (oddiy "bor" eng eski
  so'rovga yoziladi).
- **Kesh:** bitta nomer 10 daqiqa ichida qayta so'ralsa tekshiruvchi bezovta
  qilinmaydi (FAILED'dan keyingi qo'lda /check bundan mustasno).
- **Kech javob:** natija avtomatik to'g'irlanadi, mijozga uzrni admin o'zi
  yozadi (TZ v2 §6.5).
- Eski v1 xizmatini (`teleton_service.relay`) ishga tushirmang — ikkalasi
  bitta bazani buzib qo'yishi mumkin.
