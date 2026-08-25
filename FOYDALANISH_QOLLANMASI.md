# Foydalanish qo'llanmasi — rol bo'yicha

> Tizim: Kupon tekshirish v2 (qo'lda admin oqimi). Texnik hujjat:
> `TZ_v2_Qolda_Admin_Oqimi.md`, o'rnatish: `README_v2.md`.
> Bu qo'llanma **kundalik foydalanish** uchun — har kim o'z bo'limini o'qisa yetadi.

---

## 1. ADMIN (operator) uchun

Siz mijozlar bilan **avvalgidek o'z akkauntingizda** ishlaysiz. Tizim orqa
fonda kuzatib, qora ishlarni o'zi qiladi. Sizdan faqat 3 narsa:

### Kundalik oqim

1. **Mijoz nomer (va kupon) yozadi** — siz hech narsa qilmaysiz, tizim o'zi
   qayd etadi. Suhbatni odatdagidek davom ettiraverasiz.
2. **Rasmlarni mijozga tashlaysiz** (1–3 ta, odatdagidek). Tizim o'zi:
   - rasmlarni nazorat guruhiga ma'lumotlar bilan tashlaydi;
   - mijozga "tekshirish jarayonida, 1.5 soatdan keyin eslating" deb yozadi.
   
   ⚠️ Rasmlarni **15 soniya ichida** yoki bitta albom qilib tashlang — 
   kechiksangiz ikkiga bo'linib ketadi.
3. **Tekshiruv:** hech narsa qilmasangiz — 1.5 soatdan keyin tizim o'zi
   tekshiradi. Mijoz oldinroq eslatsa — mijozning **nomer yozilgan xabariga
   reply qilib** `/check` yozing. Xabar o'zi o'chadi (mijoz ko'rmaydi),
   tekshiruv darhol boshlanadi. Reply qilolmasangiz: `/check +998901234567`.

### Natija kelganda

| Natija | Nima bo'ladi | Sizning ishingiz |
|---|---|---|
| ✅ O'tdi | Mijozga avtomatik yoziladi (jonli rejimda) | Hech narsa |
| ❌ O'tmadi | Adminbotda **[📤 Mijozga yuborish] [✋ Yo'q]** tugmalari keladi | Tugmani bosing. "Yo'q" bossangiz — mijoz bilan o'zingiz gaplashasiz |
| ⚠️ Kech javob | "...aslida O'TGAN ekan, siz O'TMADI degansiz" xabari | Mijozdan **uzr so'rab to'g'ri natijani o'zingiz yozing** — tizim yozmaydi |

### Adminbotdan keladigan eslatmalar

- *"...kupon raqamini yubordi — siz rasm tashlashni unutdingiz"* — mijoz ovoz
  bergan, faqat rasm qoldi. Rasm tashlang, tamom.
- *"...nomer yubordi — uning ovozini ham olib qo'ying"* — mijoz hali ovoz
  bermagan. Ovozini oling, keyin rasm tashlang.

### Statistikangiz

`/vstats` — bugun/hafta/oy: nechta nomer, nechta o'tdi/o'tmadi. Siz faqat
**o'z** raqamlaringizni ko'rasiz.

### QILMANG ❌

- Telefonda **"Terminate all other sessions"** bosmang — tizim sizning
  akkauntingizda o'chadi, mijozlaringiz kuzatilmay qoladi. Bilmay bosib
  qo'ysangiz — darhol superadminga ayting.
- Tekshiruvchi bilan chatingizga **qo'lda aralashmang** — tizim u yerda javob
  kutayotgan bo'ladi, sizning xabaringiz chalkashtiradi.
- `/check`ni nomersiz xabarga reply qilib yubormang — "nomer topilmadi"
  xatosi keladi.
- Bir mijoz ustida ikki admin ishlamang — guruhda dublikat ogohlantirishi
  chiqadi va superadmin xabardor bo'ladi.

---

## 2. SUPERADMIN uchun

### Birinchi sozlash (tartib muhim)

1. Adminbotni nazorat guruhiga qo'shing → guruh ichida `/setgroup`
2. Barcha admin akkauntlarini ham guruhga qo'shing
3. `/setchecker <username yoki id>` — tekshiruvchi lichka
4. Shablonlar (har kategoriyada kamida 1 ta, bo'lmasa tizim tekshirmaydi):
   `/addcheckpattern OTDI bor` · `/addcheckpattern OTMADI yo'q` ·
   `/addcheckpattern XATO xato`
5. `/testcheck <haqiqiy javob>` bilan sinang
6. 1–2 kun **soya rejimida** kuzating (`/unrecognized` dan shablon to'ldiring),
   keyin `/shadow` bilan jonliga o'ting

### Buyruqlaringiz

| Buyruq | Vazifasi |
|---|---|
| `/setgroup` | Nazorat guruhini belgilash (guruh ichida yozing) |
| `/setchecker <akkaunt>` | Tekshiruvchini belgilash/almashtirish |
| `/checkpatterns` | Shablonlar ro'yxati |
| `/addcheckpattern <OTDI\|OTMADI\|XATO> <matn>` | Shablon qo'shish (formatlar: so'z, `~ichida`, `=aynan`, `re:`) |
| `/delcheckpattern <KAT> <raqam>` | Shablon o'chirish |
| `/testcheck <matn>` | Javob qanday tanilishini sinash |
| `/unrecognized` | Tanilmagan javoblar — tugma bossangiz shablonga qo'shiladi |
| `/shadow` | Soya rejimini yoqish/o'chirish |
| `/setactive <tg_id> on\|off` | Adminni faol/nofaol qilish |
| `/setreporttime HH:MM` | Kunlik hisobot vaqtini o'zgartirish (Toshkent) |
| `/uyqu off\|on [daqiqa]` | Bot ishlab turgan kompyuterning uyqu rejimi (sinov davrida; faqat Windows) |
| `/setrole <tg_id> <ROL>` | Rol berish (faqat OWNER) |
| `/admins` | Adminlar ro'yxati |
| `/vstats` | To'liq statistika (hamma admin kesimida) |

### Alertlarga qanday munosabat

| Alert | Ma'nosi | Harakat |
|---|---|---|
| 🔴 "...sessiyasi BEKOR QILINGAN" | Admin sessiyani o'chirgan/parol o'zgargan. **Mijozlari kuzatilmayapti!** | Serverda `python -m scripts.add_admin_session` bilan qayta login + restart |
| ⏳ "Tekshiruvchi javob bermayapti" | 30+ daqiqa javobsiz | Tekshiruvchiga qo'ng'iroq qiling; kerak bo'lsa `/setchecker` bilan almashtiring |
| ⚠️ "DUBLIKAT: ... ikki admin" | Bir nomerga ikki marta rasm | Adminlar bilan gaplashing — kim davom etadi |
| ⚠️ "Kech javob keldi..." | Natija avval xato yopilgan, tizim to'g'irladi | Adminning mijozdan uzr so'raganini nazorat qiling |
| ⚠️ "Guruhda reaksiya qo'yib bo'lmadi" | Guruh sozlamasida reaksiyalar yopilgan | Guruh sozlamalaridan reaksiyalarni oching |

### Boshqa vazifalar

- **Yangi admin:** serverda `python -m scripts.add_admin_session` (telefon+kod),
  keyin `systemctl restart teleton-v2`
- **Admin ketdi:** `/setactive <id> off` — case'lari muzlatiladi, ro'yxat
  sizga keladi; qaytsa `on`
- **Kunlik hisobot:** 21:00 da guruhga; sizga lichkada batafsilroq nusxa
- **Xavfsizlik:** `sessions/` papkasi = adminlarning akkauntlariga to'liq
  kirish. Serverga faqat siz va siz belgilaganlar kiradi; fayllarni hech
  kimga ko'chirmang

---

## 3. TEKSHIRUVCHI uchun

Sizga adminlarning akkauntlaridan telefon nomerlar keladi — soni cheklanmagan,
bir vaqtda bir nechtasi kelishi mumkin. Ishingiz: nomerni bazadan tekshirib
javob yozish.

### Javobni qanday yozish (uch usul, xohlaganingiz)

1. **Eng yaxshisi:** nomerli xabarga **reply** qilib javob — hech qachon
   adashmaydi
2. Nomerning **oxirgi 4 raqami** bilan: `...4567 bor`
3. Shunchaki `bor` / `yo'q` — bu holda javobingiz **eng eski** (birinchi
   kelgan) so'rovga yoziladi. Bir vaqtda ko'p so'rov turgan bo'lsa,
   adashmaslik uchun 1- yoki 2-usulni ishlating

### Qoidalar

- Kelishilgan so'zlarni ishlating: qaysi so'z "o'tgan", qaysi so'z "o'tmagan"
  degani — **superadmin adminbot orqali kiritib qo'yadi** va tizim aynan shu
  so'zlarga qarab natijani aniqlaydi. Masalan **"bor"** = o'tgan,
  **"yo'q"** = o'tmagan. Har xil yozsangiz ham tizim o'rganib boradi, lekin
  bir xillik — tezlik.
- Nomer noto'g'ri/tushunarsiz bo'lsa: **"xato"** deb yozing.
- Javob kutilayotgan chatlarda **boshqa mavzuda yozmang** — tizim keyingi
  xabaringizni ham javob deb o'qiydi.
- **Kechiksangiz ham javob yozavering** — hatto bir necha soatdan keyin ham
  tizim qabul qilib, natijani to'g'irlaydi.
- Har admin akkauntini kontaktga qo'shib qo'ying — aks holda Telegram
  xabarlarini to'sishi mumkin.

---

## 4. KUZATUVCHI (guruh a'zosi) uchun

### Guruh postini o'qish

```
📸 #C1247                    ← murojaat kodi (qidirish uchun)
👤 @username (Dilnoza)       ← mijoz
📱 +998 90 123 45 67         ← nomer
🧑‍💼 Admin: Aziz              ← kim ishlagan
🕐 14:32 · 11.08.2026        ← rasm tashlangan vaqt (Toshkent)
⏳ Tekshiruv: 16:02          ← avtomatik tekshiruv vaqti
```

Postda `⚠️ Bu nomer uchun avval ham rasm tashlangan...` qatori bo'lsa — 
ikki admin bitta mijoz ustida ishlagan (superadmin xabardor).

### Reaksiyalar lug'ati

| Reaksiya | Ma'nosi |
|---|---|
| 👍 | Ovoz o'tdi |
| 👎 | Ovoz o'tmadi |
| 🤔 (yoki ⚠️) | Javob noaniq — admin ko'rib chiqmoqda |
| 😴 (yoki ⏳) | Tekshiruvchi hali javob bermagan |
| Reaksiya yo'q | Hali tekshirilmagan |

### Reaksiyani qo'lda o'zgartirish

Postdagi reaksiyani o'zgartirsangiz (masalan 👎 → 👍), bu **rasmiy tuzatish**
sifatida bazaga yoziladi va statistikada alohida ko'rinadi. Faqat natijaga
100% ishonchingiz bo'lsa o'zgartiring.

### Kunlik hisobot

Har kuni 21:00 da guruhga tushadi: jami sonlar + har admin kesimida
(nomer / tekshirildi / o'tdi / o'tmadi / konversiya %).
