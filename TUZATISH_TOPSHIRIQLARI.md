# Tuzatish topshiriqlari — TZ v2 jonli sinov topilmalari

> **Bu fayl AI agent uchun bajarish qo'llanmasi.** Har topshiriqda: qaysi
> faylda, qaysi joyda, hozir nima yozilgan, o'rniga nima yozilishi kerak,
> nega shunday va qanday tekshirish.
>
> **Manba:** `JONLI_SINOV_HISOBOTI.md` (2026-08-16 jonli sinovi)
> **TZ:** `TZ_v2_Qolda_Admin_Oqimi.md`

---

## AGENT UCHUN UMUMIY QOIDALAR

1. **Topshiriqlarni raqam tartibida bajar** — T-1 dan boshlab. Ular
   bir-biriga bog'liq emas, lekin tartib muhimlik bo'yicha.
2. **Har topshiriqdan keyin `python -m pytest -q` ishga tushir.** Hozirgi
   holat: **291 test o'tadi**. Sonini kamaytirma.
3. **Har topshiriq uchun yangi test yoz** — "Test" bo'limida aynan nima
   tekshirilishi yozilgan. Testlarni `tests/` ichiga qo'y.
4. **Kod izohlari o'zbek tilida** — mavjud fayllardagi uslubga mos
   (nega shunday qilingani tushuntiriladi, nima qilinayotgani emas).
5. **Mavjud izohlarni o'chirma** — ular audit tarixini saqlaydi.
6. **Migratsiya kerak bo'lsa** `alembic revision` bilan yarat, qo'lda
   `ALTER TABLE` yozma. (Faqat T-9 da kerak bo'lishi mumkin.)
7. **Xizmatlarni qayta ishga tushirish kerak:** o'zgarishlar
   `adminbot_service/` da bo'lsa — adminbot, `teleton_service/` yoki
   `core/` da bo'lsa — ikkalasi ham.

**Ishga tushirish buyruqlari:**

```bash
python -m teleton_service.manual_relay
```

```bash
python -m adminbot_service.bot
```

---

# 🔴 BIRINCHI NAVBAT (jonli rejimga o'tishdan oldin)

---

## T-1. `/shadow` argumentsiz soya rejimini o'chirib yubormasin

**Muammo:** `/shadow` har safar rejimni **almashtiradi**. Admin "qaysi
rejimdaman?" deb yozgan buyruq TZ §6.4.6 dagi xavfsizlik tormozini
jimgina ochib yuboradi. Jonli sinovda 2 marta tasodifan sodir bo'ldi.

**Fayl:** `adminbot_service/bot.py`, taxminan **2207–2229-qatorlar**

### Hozir shunday

```python
@admin_router.message(Command("shadow"))
async def cmd_shadow(message: Message, current_admin: Admin) -> None:
    """TZ v2 6.4.6 — soya rejimi almashtirgichi (standart: YOQILGAN)."""
    if current_admin.role not in (AdminRole.OWNER, AdminRole.ROP):
        await message.answer("Faqat Owner/Rop soya rejimini almashtira oladi.")
        return
    async with get_session() as session:
        new_value = not await is_shadow_mode(session)
        await set_shadow_mode(session, new_value)
        await log_action(
            session, message.from_user.id, "shadow_mode", "on" if new_value else "off"
        )
    if new_value:
        await message.answer(
            "🕶 Soya rejimi <b>YOQILDI</b> — tizim taniydi, bazaga yozadi, "
            "lekin mijozga HECH NARSA yozmaydi."
        )
    else:
        await message.answer(
            "🟢 Soya rejimi <b>O'CHIRILDI</b> — natijalar endi mijozlarga "
            "yetkaziladi (B-4 oqimi bo'yicha)."
        )
```

### O'rniga shunday bo'lsin

```python
@admin_router.message(Command("shadow"))
async def cmd_shadow(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """TZ v2 6.4.6 — soya rejimi.

    ARGUMENTSIZ `/shadow` faqat HOLATNI ko'rsatadi. Avval u rejimni
    almashtirardi — jonli sinovda admin holatni bilmoqchi bo'lib yozgan
    buyruq xavfsizlik tormozini jimgina ochib yubordi. O'zgartirish endi
    faqat aniq `on`/`off` argumenti bilan (`/setreporttime` bilan bir xil
    mantiq: argumentsiz — ko'rsatadi, argument bilan — o'zgartiradi).
    """
    async with get_session() as session:
        current = await is_shadow_mode(session)

    arg = (command.args or "").strip().lower()

    if not arg:
        holat = (
            "🕶 <b>YOQILGAN</b> — mijozga hech narsa yozilmaydi."
            if current
            else "🟢 <b>O'CHIRILGAN</b> — natijalar mijozlarga yetkaziladi."
        )
        await message.answer(
            f"Soya rejimi: {holat}\n\n"
            f"O'zgartirish: <code>/shadow on</code> yoki <code>/shadow off</code>"
        )
        return

    if arg not in ("on", "off"):
        await message.answer(
            "Format: <code>/shadow on</code> yoki <code>/shadow off</code>\n"
            "(argumentsiz <code>/shadow</code> — joriy holatni ko'rsatadi)"
        )
        return

    if current_admin.role not in (AdminRole.OWNER, AdminRole.DASTURCHI):
        await message.answer(perms.denial_message(current_admin, "/shadow"))
        return

    new_value = arg == "on"
    if new_value == current:
        await message.answer(
            f"Soya rejimi allaqachon <b>{'YOQILGAN' if current else 'OCHIQ'}</b> — "
            f"o'zgarish kerak emas."
        )
        return

    async with get_session() as session:
        await set_shadow_mode(session, new_value)
        await log_action(
            session, message.from_user.id, "shadow_mode", "on" if new_value else "off"
        )

    if new_value:
        await message.answer(
            "🕶 Soya rejimi <b>YOQILDI</b> — tizim taniydi, bazaga yozadi, "
            "lekin mijozga HECH NARSA yozmaydi."
        )
    else:
        await message.answer(
            "🟢 Soya rejimi <b>O'CHIRILDI</b> — natijalar endi mijozlarga "
            "yetkaziladi.\n\n"
            "⚠️ Tanish shablonlari to'liq ekaniga ishonch hosil qiling "
            "(<code>/checkpatterns</code>) — noto'g'ri tanilgan javob endi "
            "to'g'ridan-to'g'ri mijozga ketadi."
        )
```

> **Diqqat:** `CommandObject` import qilinganini tekshir (fayl boshida
> boshqa buyruqlar uchun allaqachon bor). Rol tekshiruvi `OWNER, DASTURCHI`
> ga o'zgartirildi — sabab T-11 da.

### Test

`tests/test_admin_features.py` ga qo'sh:
- argumentsiz chaqiruv `SHADOW_MODE` qiymatini **o'zgartirmasligi**;
- `/shadow off` → `SHADOW_MODE = "0"`;
- `/shadow on` → `SHADOW_MODE = "1"`;
- noto'g'ri argument (`/shadow xyz`) → o'zgarmaydi.

Handler'ni to'g'ridan-to'g'ri chaqirish qiyin bo'lsa, mantiqni
`core/logic/settings_store.py` ga funksiya sifatida ajratib, o'shani
test qil.

---

## T-2. Soya rejimi relay qatlamida ham hurmat qilinsin

**Muammo:** `SHADOW_MODE=1` bo'lsa ham mijozga **ikki xil xabar** ketadi.
Jonli sinovda mijoz "Kuponingiz tekshirish jarayonida..." matnini **3
marta** va "Bu nomerdan oldin ovoz berilgan" ni **1 marta** oldi.

TZ §6.4.6: *"lekin **mijozga hech narsa yozmaydi**"* — istisno yo'q.

`core/logic/result_flow.py` bu qoidani to'g'ri bajaradi. Muammo faqat
`teleton_service/manual_relay.py` da — u `is_shadow_mode()` ni umuman
chaqirmaydi.

**Fayl:** `teleton_service/manual_relay.py`

### 2a. §5.3 shabloni (taxminan 321–332-qatorlar)

Hozir:

```python
        if decision.customer_text:
            # §5.3 — mijozga "tekshirish jarayonida" shablon matni (admin
            # akkauntidan). Bu chiquvchi MATN xabari — on_outgoing uni
            # rasm/buyruq emasligi uchun e'tiborsiz qoldiradi (sikl yo'q).
            try:
                await client.send_message(chat_id, decision.customer_text)
            except Exception:
                log.exception(
                    "Mijozga shablon yuborilmadi (admin=%s, chat=%s)",
                    admin.name,
                    chat_id,
                )
```

O'rniga:

```python
        if decision.customer_text:
            # §5.3 — mijozga "tekshirish jarayonida" shablon matni (admin
            # akkauntidan). Bu chiquvchi MATN xabari — on_outgoing uni
            # rasm/buyruq emasligi uchun e'tiborsiz qoldiradi (sikl yo'q).
            #
            # §6.4.6 — SOYA REJIMIDA mijozga HECH NARSA yozilmaydi. Avval bu
            # tekshiruv faqat result_flow'da bor edi, shuning uchun soya
            # rejimi yoqilgan bo'lsa ham mijoz shu matnni olaverardi.
            async with get_session() as session:
                shadow = await is_shadow_mode(session)
            if shadow:
                log.info(
                    "Soya rejimi: %s uchun §5.3 shabloni mijozga yuborilmadi.",
                    decision.case_short_code,
                )
            else:
                try:
                    await client.send_message(chat_id, decision.customer_text)
                except Exception:
                    log.exception(
                        "Mijozga shablon yuborilmadi (admin=%s, chat=%s)",
                        admin.name,
                        chat_id,
                    )
```

### 2b. `ALREADY_CONFIRMED` javobi (taxminan 392–395-qatorlar)

Hozir:

```python
                if outcome.customer_text:
                    # Faqat ALREADY_CONFIRMED holati — boshqa hamma narsada
                    # tizim jim, admin tabiiy suhbatda o'zi yozadi.
                    await event.reply(outcome.customer_text)
```

O'rniga:

```python
                if outcome.customer_text:
                    # Faqat ALREADY_CONFIRMED holati — boshqa hamma narsada
                    # tizim jim, admin tabiiy suhbatda o'zi yozadi.
                    # §6.4.6 — soya rejimida bu ham yuborilmaydi.
                    async with get_session() as session:
                        shadow = await is_shadow_mode(session)
                    if shadow:
                        await notifier.send(
                            f"🕶 (soya rejimi) {phone}: mijozga "
                            f"\"allaqachon tasdiqlangan\" javobi yuborilmadi.",
                            important=False,
                        )
                    else:
                        await event.reply(outcome.customer_text)
```

### 2c. Import qo'sh

Fayl boshidagi `from core.logic.settings_store import (...)` ro'yxatiga
`is_shadow_mode` ni qo'sh.

### Test

`tests/test_manual_case.py` yoki yangi `tests/test_shadow_mode.py`:
- `SHADOW_MODE=1` bo'lganda `process_batch` mijozga xabar
  **yubormasligi** (`client.send_message` mock — chaqirilmaganini
  tekshirish);
- `SHADOW_MODE=0` bo'lganda **yuborishi**;
- `ALREADY_CONFIRMED` uchun ham xuddi shunday.

---

## T-3. `/checkpatterns` buyrug'i relay tomonidan yeb qo'yilmasin

**Muammo:** `startswith("/check")` `/checkpatterns` va `/checkpattern`
ni ham ushlaydi. Relay bu xabarni `/check` deb qabul qilib **birinchi
navbatda o'chiradi**. Har adminda Telethon sessiyasi bo'lgani uchun bu
buyruq **hech kim uchun ishlamaydi**.

Jonli sinov: 3/3 urinishda xabar o'chirildi, adminbot javob bermadi.

**Fayl:** `teleton_service/manual_relay.py`, taxminan **492–494-qatorlar**

### Hozir shunday

```python
            text = (event.raw_text or "").strip()
            if text.lower().startswith("/check"):
                await handle_check_command(event, text)
```

### O'rniga shunday bo'lsin

```python
            text = (event.raw_text or "").strip()
            # ANIQ moslik: `startswith("/check")` `/checkpatterns` va
            # `/checkpattern` (adminbot buyruqlari) ni ham ushlab, ularni
            # o'chirib yuborardi — natijada `/checkpatterns` hech kim uchun
            # ishlamas edi (har adminda Telethon sessiyasi bor).
            # `/check@BotUsername` ko'rinishi ham qabul qilinadi.
            first_word = text.split(maxsplit=1)[0].lower() if text else ""
            if first_word.split("@")[0] == "/check":
                await handle_check_command(event, text)
```

### Test

`tests/` ga sof funksiya testi qo'sh. Buning uchun tekshiruvni alohida
yordamchiga ajratish tavsiya etiladi:

```python
def is_check_command(text: str) -> bool:
    """`/check` buyrug'ini ANIQ taniydi (`/checkpatterns` emas)."""
    if not text:
        return False
    return text.split(maxsplit=1)[0].lower().split("@")[0] == "/check"
```

Test holatlari:

| Kiritma | Kutilgan |
|---|---|
| `/check` | `True` |
| `/check +998901234567` | `True` |
| `/check@O_B_adminsbot` | `True` |
| `/CHECK` | `True` |
| `/checkpatterns` | **`False`** |
| `/checkpattern sinov` | **`False`** |
| `/checkpatterns@O_B_adminsbot` | **`False`** |
| `/testcheck bor` | `False` |
| `salom /check` | `False` |

---

## T-4. Adminbot nazorat guruhiga javob bermasin

**Muammo:** `IsAdmin` filtri faqat **yuboruvchi admin ekanini** tekshiradi,
**chat lichka ekanini tekshirmaydi**. Nazorat guruhida forward qilingan
rasmlar (admin akkauntidan ketadi) va caption (ichida nomer bor)
adminbotni ishga tushiradi.

Jonli sinov: har rasm partiyasidan keyin guruhga **3 ta chiqindi xabar**
tushdi (2× "Tushunmadim 🤔" + 1× "🔍 <nomer> — N ta murojaat:").
TZ §8.3 dagi kunlik 47 nomer bo'yicha — **kuniga ~140 ta chiqindi**.

**Fayl:** `adminbot_service/bot.py`

### 4a. Guruhda ishlashi kerak bo'lgan buyruqlarni belgila

`/setgroup` **ataylab** guruh ichida ishlashi kerak (kod izohida shunday
yozilgan), `/help` ham guruhda ishlashi mo'ljallangan
(`in_group` o'zgaruvchisi bor). Qolganlari — faqat lichka.

Fayl boshiga (router e'lonlari yonига) qo'sh:

```python
# Guruh ichida ATAYLAB ishlaydigan buyruqlar (qolganlari faqat lichkada —
# aks holda nazorat guruhi "Tushunmadim" javoblari bilan to'lib ketadi).
GROUP_ALLOWED_COMMANDS = frozenset({"setgroup", "help"})
```

### 4b. `IsAdmin` filtriga chat turi tekshiruvini qo'sh

Taxminan **169–181-qatorlar**. Hozir:

```python
    async def __call__(self, message: Message) -> bool | dict:
        if message.from_user is None:
            return False
        async with get_session() as session:
            admin = await get_admin_by_tg_id(session, message.from_user.id)
        if admin is None:
            return False
```

O'rniga (birinchi tekshiruvdan keyin qo'sh):

```python
    async def __call__(self, message: Message) -> bool | dict:
        if message.from_user is None:
            return False

        # Guruhda bot FAQAT ataylab guruh uchun mo'ljallangan buyruqlarga
        # javob beradi. Avval bunday cheklov yo'q edi: nazorat guruhiga
        # forward qilingan rasmlar va caption (ichida nomer bor) botni
        # ishga tushirib, arxiv guruhini "Tushunmadim" va qidiruv
        # natijalari bilan to'ldirardi (TZ v2 5.2 — guruh toza arxiv).
        if message.chat.type in ("group", "supergroup"):
            text = (message.text or "").strip()
            if not text.startswith("/"):
                return False
            command = text[1:].split(maxsplit=1)[0].split("@")[0].lower()
            if command not in GROUP_ALLOWED_COMMANDS:
                return False

        async with get_session() as session:
            admin = await get_admin_by_tg_id(session, message.from_user.id)
        if admin is None:
            return False
```

### 4c. Tekshir

O'zgarishdan keyin nazorat guruhiga rasm partiyasi tushganda guruhda
**faqat** forward'lar + caption bo'lishi kerak. Bot javoblari bo'lmasin.

### Test

`tests/` ga `IsAdmin` filtri uchun test:
- lichkadagi ixtiyoriy matn → o'tadi (admin bo'lsa);
- guruhdagi oddiy matn → **to'siladi**;
- guruhdagi rasm (matnsiz) → **to'siladi**;
- guruhdagi `/setgroup` → **o'tadi**;
- guruhdagi `/stats` → **to'siladi**.

`Message` ni to'liq yasash og'ir bo'lsa, chat-turi mantiqini alohida
funksiyaga ajratib (`_should_handle_in_chat(chat_type, text)`) o'shani
test qil.

---

# 🟠 IKKINCHI NAVBAT (birinchi hafta ichida)

---

## T-5. Admin va tekshiruvchi xabarlari mijoz nomeri deb qabul qilinmasin

**Muammo:** `on_incoming` da **tekshiruvchi** uchun himoya bor
(`_is_checker`), lekin **boshqa adminlar** uchun yo'q.

Jonli sinov dalillari:
1. Admin boshqa admin lichkasiga nomer yozdi → soxta `C8` case'i ochildi,
   admin **mijoz** sifatida ro'yxatga tushdi.
2. Tekshiruvchiga yuborilgan `+998935556677` so'rovi tekshiruvchining
   **o'z relay klienti** tomonidan kiruvchi mijoz xabari deb o'qildi va
   soxta alert berdi.

**Konfiguratsiya xavfi:** tekshiruvchi akkaunti kuzatilayotgan admin ham
bo'lsa, **har bir tekshiruv so'rovi** soxta case/alert yaratadi.

**Fayl:** `teleton_service/manual_relay.py`

### 5a. Adminlar to'plamini keshda tut

Fayl boshiga (global o'zgaruvchilar yonига):

```python
# §4.2 — kuzatilayotgan admin akkauntlarining tg_user_id to'plami.
# Adminlar bir-biriga (yoki tekshiruvchi lichkaga) nomer yozganda tizim
# uni MIJOZ deb qabul qilmasligi kerak: jonli sinovda tekshiruvchiga
# ketgan har bir so'rov tekshiruvchining o'z klienti tomonidan "yangi
# mijoz nomeri" deb o'qilib, soxta case va alert yaratardi.
_admin_tg_ids: set[int] = set()


async def _refresh_admin_tg_ids() -> None:
    global _admin_tg_ids
    async with get_session() as session:
        admins = await list_admins(session)
    _admin_tg_ids = {a.tg_user_id for a in admins}
```

### 5b. `main()` da to'ldir

`main()` ichida, `ensure_admins_seeded(...)` dan **keyin**:

```python
    await _refresh_admin_tg_ids()
```

Yangi admin qo'shilishi kamdan-kam bo'ladi va jarayon qayta ishga
tushiriladi, shuning uchun davriy yangilash shart emas. Agar xohlasang
`multi.health_loop()` yonида soatiga bir marta yangilaydigan vazifa
qo'shishing mumkin.

### 5c. `on_incoming` da tekshir

`_is_checker` tekshiruvidan **keyin**, `extract_phone` dan **oldin**:

```python
            if await _is_checker(tg_user_id, tg_username):
                await check_engine.handle_checker_reply(
                    admin.id, text, reply_to_msg_id=event.message.reply_to_msg_id
                )
                return

            # Xabar BOSHQA ADMIN akkauntidan kelgan bo'lsa — bu mijoz emas,
            # xizmat ichidagi yozishma (masalan tekshiruvchiga ketgan
            # so'rovning o'zi, yoki adminlarning o'zaro suhbati). Case
            # ochilmaydi, alert berilmaydi.
            if tg_user_id in _admin_tg_ids:
                log.debug(
                    "Admin akkauntidan kelgan xabar e'tiborsiz qoldirildi "
                    "(kuzatuvchi admin=%s, yuboruvchi tg_id=%s).",
                    admin.name,
                    tg_user_id,
                )
                return
```

### 5d. `/setchecker` da ogohlantirish

**Fayl:** `adminbot_service/bot.py`, `cmd_setchecker` (taxminan 2070-qator)

Tekshiruvchi belgilangandan keyin, agar o'sha akkaunt `admins` jadvalida
**faol sessiya bilan** bo'lsa, javobga ogohlantirish qo'sh:

```
⚠️ DIQQAT: bu akkaunt ayni vaqtda kuzatilayotgan admin hamdir.
Tavsiya: tekshiruvchi uchun ALOHIDA akkaunt ishlating — aks holda
unga ketgan so'rovlar o'sha akkauntning o'z klienti tomonidan
qayta o'qiladi.
```

### Test

`tests/test_manual_case.py` ga:
- admin `tg_user_id` idan kelgan nomerli xabar → case **ochilmaydi**,
  alert **chiqmaydi**;
- oddiy mijoz `tg_user_id` idan kelgan xabar → case ochiladi (regressiya).

---

## T-6. Case'ning BARCHA partiyalari natija olsin

**Muammo:** natija chiqqanda faqat **oxirgi** partiya belgilanadi.
Oldingi guruh postlari abadiy `PENDING` va reaksiyasiz qoladi.

TZ §6.1a bo'yicha admin rasmni qayta tashlashi **normal holat**
("taymer oxirgi rasm vaqtidan qayta hisoblanadi") — demak bu muntazam
sodir bo'ladi va §8.2 statistikasini buzadi.

Jonli sinov (C7, natija PASSED):

| Partiya | Guruh posti | outcome | Reaksiya |
|---|---|---|---|
| #1 | 56 | `PENDING` | yo'q |
| #2 | 62 | `PENDING` | yo'q |
| #3 | 68 | `PASSED` | 👍 |

**Fayl:** `core/logic/result_flow.py`, taxminan **232–262-qatorlar**

### Hozir shunday

```python
    async def _update_batch_and_react(
        self, session, request: CheckRequest, outcome: BatchOutcome
    ) -> None:
        result = await session.execute(
            select(ScreenshotBatch)
            .where(ScreenshotBatch.case_id == request.case_id)
            .order_by(ScreenshotBatch.id.desc())
        )
        batch = result.scalars().first()
        if batch is None:
            return  # rasmsiz tekshirilgan case — guruh posti yo'q

        batch.outcome = outcome
        batch.outcome_source = OutcomeSource.AUTO
        await session.commit()

        if batch.group_chat_id is None or batch.group_message_id is None:
            return  # guruhga tushmagan partiya

        emoji = REACTION_BY_OUTCOME[outcome]
        ok = await self.set_reaction(
            batch.admin_id, batch.group_chat_id, batch.group_message_id, emoji
        )
        if not ok:
            # §7.3 — reaksiya qo'yilmasa natija bazada saqlanadi + alert.
            await self.alert_sink(
                f"⚠️ Guruhda reaksiya qo'yib bo'lmadi (partiya #{batch.id}, "
                f"{emoji}) — guruh sozlamalarida reaksiyalar yopilgan bo'lishi "
                f"mumkin. Natija bazada saqlangan.",
                True,
            )
```

### O'rniga shunday bo'lsin

```python
    async def _update_batch_and_react(
        self, session, request: CheckRequest, outcome: BatchOutcome
    ) -> None:
        """Case'ning BARCHA partiyalarini natija bilan belgilaydi.

        Avval faqat OXIRGI partiya belgilanardi. Lekin §6.1a bo'yicha
        admin rasmni qayta tashlashi normal holat (taymer oxirgi rasm
        vaqtidan qayta hisoblanadi) — natijada guruhda belgisiz, abadiy
        PENDING postlar qolib ketardi va §8.2 statistikasi buzilardi.

        Reaksiya QO'LDA o'zgartirilgan partiyalarga tegilmaydi (§7.3 —
        odam qarori avtomatikadan ustun).
        """
        result = await session.execute(
            select(ScreenshotBatch)
            .where(ScreenshotBatch.case_id == request.case_id)
            .order_by(ScreenshotBatch.id)
        )
        batches = list(result.scalars().all())
        if not batches:
            return  # rasmsiz tekshirilgan case — guruh posti yo'q

        targets = []
        for batch in batches:
            if batch.outcome_source == OutcomeSource.MANUAL:
                continue  # odam qo'lda belgilagan — tegmaymiz
            batch.outcome = outcome
            batch.outcome_source = OutcomeSource.AUTO
            targets.append(batch)
        await session.commit()

        emoji = REACTION_BY_OUTCOME[outcome]
        for batch in targets:
            if batch.group_chat_id is None or batch.group_message_id is None:
                continue  # guruhga tushmagan partiya
            ok = await self.set_reaction(
                batch.admin_id, batch.group_chat_id, batch.group_message_id, emoji
            )
            if not ok:
                # §7.3 — reaksiya qo'yilmasa natija bazada saqlanadi + alert.
                await self.alert_sink(
                    f"⚠️ Guruhda reaksiya qo'yib bo'lmadi (partiya #{batch.id}, "
                    f"{emoji}) — guruh sozlamalarida reaksiyalar yopilgan "
                    f"bo'lishi mumkin. Natija bazada saqlangan.",
                    True,
                )
```

> **Eslatma:** `set_reaction` chaqiruvlari orasida TZ §4.5 bo'yicha
> tabiiy pauza kerak bo'lishi mumkin. Agar bitta case'da 3+ partiya
> bo'lsa, `await asyncio.sleep(random.uniform(0.5, 1.5))` qo'shishni
> ko'rib chiq (bu modul hozir `asyncio` import qilmaydi).

### Test

`tests/test_result_flow.py` ga:
- bitta case'da **3 ta** partiya bo'lsa, natija chiqqanda **uchalasi**
  ham `outcome` oladi va **uchalasiga** reaksiya qo'yiladi;
- `outcome_source=MANUAL` bo'lgan partiya **o'zgarmaydi**;
- `group_message_id IS NULL` bo'lgan partiyaga reaksiya urinilmaydi.

---

## T-7. `/stats` oddiy adminga butun tizim ma'lumotini ko'rsatmasin

**Muammo:** TZ §8.4 — *"**Oddiy admin** — faqat o'z statistikasini
ko'radi"*. `/vstats` va `/problems` bu qoidani to'g'ri bajaradi, eski
`/stats` ekrani esa **hammaga hamma narsani** ko'rsatadi.

Jonli sinov — `ADMIN` rolidagi akkaunt yubordi:

```
Bugungi murojaatlar: 2       <- biri boshqa adminniki
CHECK_SENT: 1                <- boshqa adminning case'i
❌ Rad etildi: 3
```

**Qo'shimcha:** matn oxirida eskirgan v1 izohi turibdi — *"hozircha
bitta Teleton akkaunti ishlaydi"* — aslida 3 ta sessiya ishlayapti.

### 7a. `gather_stats` ga ko'rish cheklovi qo'sh

**Fayl:** `core/logic/stats.py`

`gather_stats` hozir hech qanday cheklov qabul qilmaydi. Yangi
ixtiyoriy parametrlar qo'sh (mavjud chaqiruvlar buzilmasin):

```python
async def gather_stats(
    session: AsyncSession,
    viewer_admin_id: int | None = None,
    can_see_all: bool = True,
) -> Stats:
    """TZ 10-bo'lim + §8.4 ko'rish cheklovi.

    `can_see_all=False` bo'lsa faqat shu adminga biriktirilgan (yoki hali
    hech kimga biriktirilmagan) mijozlarning case'lari hisoblanadi —
    `list_cases_by_statuses` dagi bilan bir xil qoida.
    """
```

Uchala so'rovga ham (`today_count`, `status_rows`, `problem_count`)
`User` ga JOIN va `_visible_to` shartini qo'sh. `_visible_to`
`core/logic/case_admin.py:148` da — uni import qilib ishlat yoki
umumiy joyga ko'chir.

Namuna (bitta so'rov uchun):

```python
    from core.logic.case_admin import _visible_to
    from core.models import User

    def _scope(stmt):
        if can_see_all:
            return stmt
        return _visible_to(stmt.join(User, Case.user_id == User.id),
                           viewer_admin_id, can_see_all)

    today_count = (
        await session.execute(
            _scope(select(func.count()).select_from(Case))
            .where(Case.created_at >= today_start)
        )
    ).scalar_one()
```

> `_visible_to` nomi pastki chiziq bilan boshlangani uchun uni
> `visible_to` deb qayta nomlab, `case_admin.py` dagi chaqiruvlarni
> yangilash toza yechim bo'ladi.

### 7b. Handler'ni yangila

**Fayl:** `adminbot_service/bot.py`, taxminan **383–388-qatorlar**

Hozir:

```python
@admin_router.message(Command("stats"))
@admin_router.message(F.text == kb.BTN_STATS)
async def show_stats(message: Message) -> None:
    async with get_session() as session:
        stats = await gather_stats(session)
    await message.answer(views.stats_text(stats))
```

O'rniga:

```python
@admin_router.message(Command("stats"))
@admin_router.message(F.text == kb.BTN_STATS)
async def show_stats(message: Message, current_admin: Admin) -> None:
    # §8.4 — oddiy admin faqat o'zinikini ko'radi (`/vstats` va
    # `/problems` allaqachon shunday; bu ekran ochiq qolib ketgan edi).
    can_all = can_see_everything(current_admin)
    async with get_session() as session:
        stats = await gather_stats(
            session, viewer_admin_id=current_admin.id, can_see_all=can_all
        )
    await message.answer(views.stats_text(stats, own_only=not can_all))
```

### 7c. Eskirgan matnni almashtir

**Fayl:** `adminbot_service/views.py`, taxminan **166–180-qatorlar**

```python
def stats_text(stats, own_only: bool = False) -> str:
    if stats.by_status:
        rows = "\n".join(
            f"  {status_label(CaseStatus(s))}: <b>{c}</b>" for s, c in stats.by_status.items()
        )
    else:
        rows = "  (hali murojaat yo'q)"
    sarlavha = "📊 <b>Statistika</b>"
    if own_only:
        sarlavha += " <i>(faqat sizniki)</i>"
    return (
        f"{sarlavha}\n\n"
        f"Bugungi murojaatlar: <b>{stats.today_count}</b>\n"
        f"Ochiq muammoli holatlar: <b>{stats.problem_count}</b>\n\n"
        f"Holat bo'yicha (barcha vaqt):\n{rows}\n\n"
        "<i>Admin kesimidagi batafsil ko'rsatkichlar uchun /vstats.</i>"
    )
```

### Test

`tests/test_stats_expansion.py` ga:
- ikki admin va ikki mijoz yaratilsin;
- `can_see_all=False` bilan chaqirilganda faqat o'z mijozining
  case'lari hisoblanishi;
- `can_see_all=True` bilan hammasi hisoblanishi;
- biriktirilmagan (`assigned_admin_id IS NULL`) mijoz ikkalasiga ham
  ko'rinishi.

---

## T-8. TZ §4.3 talab qilgan "Sessiyalar" bo'limini qo'sh

**Muammo:** TZ §4.3: *"Adminbotda `Sessiyalar` bo'limi: har akkaunt
holati, oxirgi faollik vaqti."* — bunday buyruq ham, tugma ham yo'q.

Baza qatlami **tayyor** — `admin_sessions` jadvalida `status`,
`last_seen_at`, `last_error` to'ldirilib turadi. Faqat ko'rish oynasi
qurilmagan.

### 8a. Yangi buyruq

**Fayl:** `adminbot_service/bot.py`

`/setchecker` yonига (taxminan 2070-qator atrofi) qo'sh:

```python
@admin_router.message(Command("sessions"))
async def cmd_sessions(message: Message, current_admin: Admin) -> None:
    """TZ v2 4.3 — har admin akkauntining sessiya holati.

    Sessiya o'lsa o'sha adminning mijozlari JIMGINA yo'qoladi — shuning
    uchun holatni ko'rish imkoni bo'lishi shart (alert kelib, keyin
    esdan chiqib ketishi mumkin).
    """
    async with get_session() as session:
        rows = await list_admin_sessions(session)

    if not rows:
        await message.answer(
            "Hech qanday admin sessiyasi ulanmagan.\n\n"
            "Qo'shish: serverda <code>python -m scripts.add_admin_session</code>"
        )
        return

    await message.answer(views.sessions_text(rows))
```

### 8b. Baza yordamchisi

**Fayl:** `core/logic/admins.py` (yoki yangi `core/logic/sessions.py`)

```python
async def list_admin_sessions(session: AsyncSession) -> list[tuple[AdminSession, Admin]]:
    """Har sessiya + egasi (TZ v2 4.3 ko'rish oynasi uchun)."""
    result = await session.execute(
        select(AdminSession, Admin)
        .join(Admin, AdminSession.admin_id == Admin.id)
        .order_by(Admin.id)
    )
    return [(s, a) for s, a in result.all()]
```

### 8c. Ko'rinish

**Fayl:** `adminbot_service/views.py`

```python
_SESSION_BELGI = {
    "CONNECTED": "🟢",
    "DISCONNECTED": "🟡",
    "AUTH_LOST": "🔴",
}


def sessions_text(rows) -> str:
    """TZ v2 4.3 — sessiya holati jadvali."""
    lines = ["🔌 <b>Admin sessiyalari</b>", ""]
    for sess, admin in rows:
        belgi = _SESSION_BELGI.get(sess.status.value, "⚪️")
        lines.append(f"{belgi} <b>{display_name(admin)}</b>")
        lines.append(f"    {sess.phone or '—'} · <code>{sess.session_name}</code>")
        lines.append(f"    Holat: {sess.status.value}")
        if sess.last_seen_at:
            lines.append(f"    Oxirgi faollik: {to_tashkent(sess.last_seen_at):%H:%M · %d.%m.%Y}")
        if sess.last_error:
            lines.append(f"    ⚠️ {sess.last_error[:120]}")
        lines.append("")
    lines.append(
        "<i>🔴 AUTH_LOST — qayta login kerak: serverda "
        "<code>python -m scripts.add_admin_session</code></i>"
    )
    return "\n".join(lines)
```

`to_tashkent` ni `core.logic.screenshots` dan import qil.

### 8d. Ruxsat jadvaliga qo'sh

**Fayl:** `core/logic/permissions.py`, `COMMANDS` ro'yxatiga:

```python
        _p("sessions", _MANAGE | _TECH, "Texnik sozlash", "/sessions",
           "Admin akkauntlari sessiya holati"),
```

### 8e. Menyuga tugma (ixtiyoriy)

`adminbot_service/keyboards.py` dagi "⚙️ Sozlamalar" bo'limiga
"🔌 Sessiyalar" tugmasini qo'shsang qulay bo'ladi.

### Test

`tests/` ga:
- `list_admin_sessions` uchala sessiyani egasi bilan qaytarishi;
- `sessions_text` `AUTH_LOST` holatini 🔴 bilan ko'rsatishi;
- sessiya yo'q bo'lganda handler tushunarli xabar berishi.

---

## T-9. `permissions.py` bilan handler tekshiruvlarini birlashtir

**Muammo:** `core/logic/permissions.py` o'z izohida **"yagona haqiqat
manbai"** deb yozilgan, lekin handler'lar o'z, boshqacha tekshiruvini
yuritadi:

| Buyruq | `permissions.py` | Handler ichida |
|---|---|---|
| `/setgroup` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/setchecker` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/shadow` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/addcheckpattern` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |
| `/delcheckpattern` | `_TECH` = OWNER, **DASTURCHI** | `not in (OWNER, ROP)` |

**Oqibati:** `DASTURCHI` bu buyruqlarni `/help` da **ko'radi**,
middleware uni **o'tkazadi**, handler esa *"Faqat Owner/Rop..."* deb
**rad etadi**. Aynan `permissions.py` oldini olmoqchi bo'lgan holat.

### Bajarish

`RolePermission` middleware allaqachon `perms.can_use_command()` ni
tekshiradi va rad etilganda `perms.denial_message()` yuboradi. Demak
handler ichidagi takroriy tekshiruvlar **ortiqcha** — ularni
**o'chirish** kerak.

Quyidagi handler'lardan `if current_admin.role not in (...)` blokini
**butunlay olib tashla** (middleware ishini bajaradi):

- `cmd_setgroup` (~1616-qator)
- `cmd_setchecker` (~2070-qator)
- `cmd_shadow` (~2210-qator) — T-1 da qayta yozilgan variantda
  `perms.denial_message` ishlatilgan; middleware ishlagach uni ham
  olib tashlash mumkin
- `cmd_addcheckpattern` (~2120-qator)
- `cmd_delcheckpattern` (~2152-qator)

Handler'lardan biror birida rol tekshiruvi **saqlanishi kerak** deb
hisoblasang, u holda `permissions.py` dagi to'plamni o'zgartir
(`_TECH` → `_MANAGE`), **ikkovini bir xil qil**.

> **Qaror kerak:** bu buyruqlar `DASTURCHI` ga ochiq bo'lsinmi
> (`permissions.py` shunday deydi, TZ 14 "Dasturchi — texnik sozlash,
> botlar, shablonlar" ham shunga mos) yoki faqat `OWNER/ROP` gami
> (handler shunday deydi)? **Tavsiya: `permissions.py` to'g'ri** —
> TZ 14 bo'linishiga mos. Handler tekshiruvlarini o'chir.

### Test

`tests/test_permissions.py` ga **zidlikni ushlaydigan** test qo'sh:

```python
def test_handler_checks_do_not_contradict_permission_table():
    """Handler ichida qo'lda yozilgan rol tekshiruvi qolmaganini
    kafolatlaydi — aks holda jadval va amaliyot yana ajralib ketadi."""
    import pathlib, re
    manba = pathlib.Path("adminbot_service/bot.py").read_text(encoding="utf-8")
    taqiqlangan = re.findall(r"role not in \([^)]*\)", manba)
    assert not taqiqlangan, (
        "Handler ichida qo'lda rol tekshiruvi topildi — ruxsat faqat "
        f"core/logic/permissions.py orqali berilishi kerak: {taqiqlangan}"
    )
```

---

## T-10. Dublikat ogohlantirishi bir xil case uchun chiqmasin

**Muammo:** dublikat faqat **nomer** bo'yicha aniqlanadi — case va admin
hisobga olinmaydi. Admin o'sha mijozga ikkinchi marta rasm tashlasa
ham (§6.1a bo'yicha **normal holat**) dublikat deb belgilanadi va
noto'g'ri alert ketadi:

```
⚠️ DUBLIKAT: +998 90 111 22 33 uchun avval ham rasm tashlangan
(partiya #1, admin_id=1). Yangi partiya: C7 (admin: 6644467393).
Ikki admin bitta mijoz ustida ishlayotgan bo'lishi mumkin.   <-- NOTO'G'RI
```

Bu yerda admin ham, case ham **bitta**. Caption'da post o'z case'iga
havola qiladi (`— #C7`), TZ §5.4 namunasi esa **boshqa** case'ga
(`#C1189`).

**Fayl:** `core/logic/screenshots.py`

### 10a. Dublikat qidiruvidan o'sha case'ni chiqar

Taxminan **213–219-qatorlar**:

```python
    async def _find_previous_batch(self, session, phone: str) -> ScreenshotBatch | None:
        result = await session.execute(
            select(ScreenshotBatch)
            .where(ScreenshotBatch.phone == phone)
            .order_by(ScreenshotBatch.id.desc())
        )
        return result.scalars().first()
```

O'rniga:

```python
    async def _find_previous_batch(
        self, session, phone: str, exclude_case_id: int
    ) -> ScreenshotBatch | None:
        """§5.4 — dublikat = shu nomer uchun BOSHQA case'da tashlangan partiya.

        O'sha case'ning o'ziga qayta rasm tashlash dublikat EMAS: §6.1a
        buni normal holat deb belgilaydi ("admin rasmni ikkinchi marta
        tashlasa — taymer oxirgi rasm vaqtidan qayta hisoblanadi").
        Avval bu ajratilmagani uchun har qayta tashlashda superadminga
        "ikki admin bitta mijoz ustida ishlayapti" degan noto'g'ri alert
        ketardi.
        """
        result = await session.execute(
            select(ScreenshotBatch)
            .where(
                ScreenshotBatch.phone == phone,
                ScreenshotBatch.case_id != exclude_case_id,
            )
            .order_by(ScreenshotBatch.id.desc())
        )
        return result.scalars().first()
```

### 10b. Chaqiruvni yangila

Taxminan **110-qator**:

```python
            prev = await self._find_previous_batch(session, case.phone)
```

→

```python
            prev = await self._find_previous_batch(session, case.phone, case.id)
```

### 10c. Alert matnini aniqlashtir

Taxminan **159–166-qatorlar** — `prev.admin_id` bilan joriy `admin_id`
ni solishtirib matnni ajrat:

```python
            if prev is not None:
                prev_admin = await session.get(Admin, prev.admin_id)
                prev_nomi = prev_admin.name if prev_admin else f"admin_id={prev.admin_id}"
                if prev.admin_id == admin_id:
                    sabab = (
                        f"O'SHA admin ({admin_name}) bu nomer uchun boshqa "
                        f"case'da ham rasm tashlagan — ikki marta kiritilgan "
                        f"bo'lishi mumkin."
                    )
                else:
                    sabab = (
                        f"IKKI ADMIN bitta mijoz ustida ishlayapti: "
                        f"{prev_nomi} va {admin_name}."
                    )
                await self.alert_sink(
                    f"⚠️ DUBLIKAT: {format_phone_pretty(case.phone)} — "
                    f"avvalgi partiya #{prev.id}, yangi partiya "
                    f"{case.short_code or case.id}. {sabab}",
                    True,
                )
```

### Test

`tests/` dagi rasm oqimi testlariga:
- **bir xil** case'ga ikkinchi partiya → `is_duplicate=False`, alert yo'q;
- **boshqa** case'ga (o'sha nomer) partiya → `is_duplicate=True`, alert bor;
- boshqa **admin** boshqa case'da → alert matnida "IKKI ADMIN" bo'lishi.

---

## T-11. OWNER avtomatik ko'tarilishi ko'rinadigan bo'lsin

**Muammo:** `ensure_owner_exists` faol OWNER topmasa `.env` dagi
birinchi adminni jimgina OWNER qiladi:

- `audit_log` ga **yozilmaydi** (faqat `log.warning`)
- adminga **xabar berilmaydi**

Jonli sinovda: foydalanuvchi `/setrole 6644467393 DASTURCHI` bajarib
tasdiq oldi (audit #22), keyin jarayon qayta ishga tushganda rol
**jimgina OWNER ga qaytdi**. Foydalanuvchi o'zini DASTURCHI deb
o'ylab yuradi.

Mexanizmning o'zi **to'g'ri** (tizim qulflanib qolmasligi uchun kerak) —
faqat **ko'rinmasligi** muammo.

**Fayl:** `core/logic/admins.py`, taxminan **57–70-qatorlar**

### Hozir shunday

```python
        if candidate is not None:
            candidate.role = AdminRole.OWNER
            candidate.is_active = True
            await session.commit()
            await session.refresh(candidate)
            log.warning(
                "Tizimda faol OWNER topilmadi — %s (tg_id=%s) OWNER'ga ko'tarildi. "
                "Aks holda hech kim /setrole ishlata olmay, tizim qulflanib qolardi.",
                candidate.name,
                candidate.tg_user_id,
            )
            return candidate
```

### O'rniga shunday bo'lsin

```python
        if candidate is not None:
            eski_rol = candidate.role.value
            candidate.role = AdminRole.OWNER
            candidate.is_active = True
            await session.commit()
            await session.refresh(candidate)
            # Audit jurnaliga YOZILADI: avval bu faqat log faylida qolar edi,
            # natijada `/setrole` bilan o'zini pasaytirgan admin keyingi
            # restartda jimgina OWNER bo'lib qolar va buni bilmasdi.
            await log_action(
                session,
                candidate.tg_user_id,
                "auto_promote_owner",
                f"{eski_rol} -> OWNER (tizimda faol OWNER qolmagan edi)",
            )
            log.warning(
                "Tizimda faol OWNER topilmadi — %s (tg_id=%s) %s rolidan "
                "OWNER'ga ko'tarildi. Aks holda hech kim /setrole ishlata "
                "olmay, tizim qulflanib qolardi.",
                candidate.name,
                candidate.tg_user_id,
                eski_rol,
            )
            return candidate
```

`log_action` ni `core.logic.audit` dan import qil (aylanma import
bo'lsa, funksiya ichida import qil).

### Qo'shimcha: `/setrole` da ogohlantirish

**Fayl:** `adminbot_service/bot.py`, `cmd_setrole` (~1556-qator)

Agar admin **yagona faol OWNER** ni boshqa rolga o'tkazmoqchi bo'lsa,
javobga qo'sh:

```
⚠️ Siz tizimdagi YAGONA faol Owner edingiz. Keyingi ishga tushishda
tizim sizni avtomatik Owner'ga qaytaradi (aks holda hech kim rol
bera olmay qoladi). Boshqa odamni Owner qilib, keyin o'zingizni
pasaytiring.
```

### Test

`tests/test_stats_expansion.py` da `ensure_owner_exists` testlari bor —
ularga qo'sh:
- ko'tarilish sodir bo'lganda `audit_log` da `auto_promote_owner`
  yozuvi paydo bo'lishi;
- OWNER allaqachon bor bo'lsa audit yozuvi **qo'shilmasligi**.

---

# 🟡 UCHINCHI NAVBAT

---

## T-12. Guruh caption'ida admin ismi raqam bo'lib qolmasin

**Muammo:** `refresh_admin_identity` (`core/logic/admins.py:102`) **faqat
adminbot middleware'idan** chaqiriladi (`bot.py:188`). Relay uni hech
qachon chaqirmaydi. Adminbotga hech qachon yozmagan admin barcha guruh
caption'larida raqam bo'lib qolaveradi.

Jonli dalil:

```
🧑‍💼 Admin: 6644467393              <- adminbotga yozishdan oldin
🧑‍💼 Admin: Abduqahhor Suvonov      <- yozgandan keyin
```

TZ §5.2 namunasi ism talab qiladi: `🧑‍💼 Admin: Aziz Karimov`.

**Fayl:** `teleton_service/multi_client.py`, `_start_one` (taxminan
**99–150-qatorlar**)

### Bajarish

`await client.is_user_authorized()` muvaffaqiyatli bo'lgandan keyin,
`wire_handlers(client, admin)` dan **oldin** qo'sh:

```python
        # TZ v2 5.2 — guruh caption'ida admin ISMI ko'rinishi kerak.
        # `refresh_admin_identity` faqat adminbot muloqotidan chaqirilardi,
        # shuning uchun adminbotga hech qachon yozmagan admin caption'larda
        # raqam bo'lib qolaverardi. Sessiya ulanganda ism allaqachon
        # qo'limizda — o'shanda yangilaymiz.
        try:
            me = await client.get_me()
            full = " ".join(
                p for p in (me.first_name, me.last_name) if p
            ) or None
            async with self.session_factory() as db:
                admin_row = await db.get(Admin, admin.id)
                if admin_row is not None:
                    await refresh_admin_identity(db, admin_row, full, me.username)
                    admin.name = admin_row.name
        except Exception:
            log.warning(
                "Admin %s ismini Telegram'dan yangilab bo'lmadi.", admin.id
            )
```

`refresh_admin_identity` va `Admin` ni import qil.
`ManagedClient(admin_name=admin.name, ...)` yaratilishi **shu koddan
keyin** bo'lishiga e'tibor ber (aks holda eski nom keshda qoladi) —
kerak bo'lsa `managed` yaratilishini pastga ko'chir.

### Test

- `refresh_admin_identity` ning o'zi allaqachon testlangan
  (`tests/test_stats_expansion.py:230`);
- yangi test: `_start_one` dan keyin `admin.name` raqam emasligini
  soxta (mock) klient bilan tekshir.

---

## T-13. Caption'ga mijozga `tg://user?id=` havolasini qo'sh

**Muammo:** TZ §5.2: *"Mijozga havola: `tg://user?id=<tg_user_id>`"*.
Amalda oddiy matn yoziladi — username bo'lmasa `id:6644467393`, u ham
bosiladigan havola emas. Nazorat guruhida mijozga tez o'tish imkoni yo'q.

**Fayl:** `core/logic/screenshots.py`, `_build_caption` (taxminan
**256–263-qatorlar**)

### Hozir shunday

```python
        customer = (
            f"@{user.tg_username} ({user.display_name})"
            if user.tg_username and user.display_name
            else f"@{user.tg_username}"
            if user.tg_username
            else user.display_name or f"id:{user.tg_user_id}"
        )
```

### O'rniga shunday bo'lsin

```python
        # TZ v2 5.2 — mijozga BOSILADIGAN havola. Avval oddiy matn edi;
        # username'siz mijozga guruhdan o'tishning iloji yo'q edi.
        ism = user.display_name or (f"@{user.tg_username}" if user.tg_username else "mijoz")
        havola = f'<a href="tg://user?id={user.tg_user_id}">{ism}</a>'
        customer = f"{havola} (@{user.tg_username})" if user.tg_username else havola
```

> ⚠️ **MUHIM:** caption Telethon orqali yuboriladi
> (`manual_relay.py:302` — `client.send_message(group_chat_id, caption)`).
> HTML ishlashi uchun `parse_mode='html'` **aniq berilishi kerak**:
>
> ```python
> caption_msg = await client.send_message(
>     decision.group_chat_id, decision.caption, parse_mode="html"
> )
> ```
>
> Aks holda `<a href=...>` teglari xom matn bo'lib ko'rinadi.
> Caption ichidagi boshqa matnlar (ism, username) HTML uchun
> **ekranlanishi** kerak — `html.escape()` ishlat, aks holda ismida
> `<` bo'lgan mijoz caption'ni buzadi.

### Test

- `_build_caption` natijasida `tg://user?id=` borligini tekshir;
- ismida `<`, `&` bo'lgan mijoz uchun ekranlanish to'g'riligini tekshir;
- username yo'q mijoz uchun ham havola chiqishini tekshir.

---

## T-14. Kupon to'g'ri case'ga yozilsin

**Muammo:** kupon **mijozning oxirgi ochiq case'iga** bog'lanadi —
xabardagi nomerga emas.

Jonli dalil: mijoz `907778899 kuponim 123456` yozdi. Nomer rad etildi
(boshqa case ochiq edi), lekin kupon `123456` **eski case'ga**
(`998901112233`) yozildi:

```
(7, 'C7', '998901112233', 'NUMBER_RECEIVED', '123456', ...)
```

TZ §9.2 kuponni "dalil" va "mijoz ovoz berganligi signali" deb
belgilaydi — noto'g'ri nomerga bog'langan kupon ikkala vazifani ham
buzadi (§6.1a2 dagi rasmsizlik eslatmasi noto'g'ri variantda chiqadi).

**Fayllar:** `core/logic/manual_case.py` + `teleton_service/manual_relay.py`

### 14a. `handle_coupon_detected` ga nomer parametri qo'sh

`core/logic/manual_case.py`, taxminan **131–155-qatorlar**:

```python
    async def handle_coupon_detected(
        self, tg_user_id: int, coupon: str, phone: str | None = None
    ) -> None:
        """Mijoz kupon raqamini yozganda — FAQAT saqlanadi (TZ v2 9.2).

        `phone` berilgan bo'lsa (kupon nomer bilan BITTA xabarda kelgan),
        kupon aynan o'sha nomerli case'ga yoziladi. Avval kupon doim
        "oxirgi ochiq case"ga bog'lanardi — natijada mijoz boshqa nomer
        + kupon yozganda kupon ESKI case'ga tushib qolardi va §6.1a2
        dagi rasmsizlik eslatmasi noto'g'ri variantda chiqardi.
        """
        async with self.session_factory() as session:
            user = await self._get_user(session, tg_user_id)
            if user is None or user.is_blocked:
                return

            case = None
            if phone is not None:
                result = await session.execute(
                    select(Case)
                    .where(Case.user_id == user.id, Case.phone == phone)
                    .order_by(Case.id.desc())
                )
                case = result.scalars().first()
                if case is not None and case.status not in V2_OPEN_STATUSES:
                    case = None
                if case is None:
                    # Nomer aniq berilgan, lekin unga tegishli ochiq case
                    # yo'q — kuponni BOSHQA case'ga yozib qo'yish xato
                    # dalil yaratadi, shuning uchun e'tiborsiz qoldiramiz.
                    log.info(
                        "Kupon %s uchun ochiq case topilmadi — saqlanmadi.", phone
                    )
                    return
            else:
                case = await self._get_latest_case(session, user.id)
                if case is None or case.status not in V2_OPEN_STATUSES:
                    return

            if case.coupon is not None:
                return  # birinchi kupon saqlangan — keyingilari e'tiborsiz

            case.coupon = coupon
            case.coupon_at = datetime.datetime.utcnow()
            await session.commit()
            log.info(
                "Case %s uchun kupon saqlandi (signal: mijoz ovoz bergan).",
                case.short_code or case.id,
            )
```

### 14b. Chaqiruvni yangila

`teleton_service/manual_relay.py`, taxminan **389–391-qatorlar** —
nomer va kupon bitta xabarda kelgan holat:

```python
                coupon = extract_coupon(text)
                if coupon is not None:
                    await case_manager.handle_coupon_detected(
                        tg_user_id, coupon, phone=phone
                    )
```

**401–404-qatorlar** (faqat kupon, nomersiz) — o'zgarishsiz qoladi:
kupon oxirgi ochiq case'ga bog'lanadi, bu to'g'ri.

### Test

`tests/test_manual_case.py` ga:
- ochiq case A turganda mijoz "B_nomer kupon" yozsa → kupon A ga
  **yozilmasligi**;
- kupon o'sha case nomeri bilan kelsa → **yozilishi**;
- nomersiz kupon → oxirgi ochiq case'ga yozilishi (regressiya).

---

## T-15. §5.3 shabloni mijozga takror yuborilmasin

**Muammo:** har rasm partiyasidan keyin mijozga bir xil matn qayta
ketadi. Jonli sinovda 3 partiya → mijoz "Kuponingiz tekshirish
jarayonida..." matnini **3 marta** oldi. Admin bir necha marta rasm
tashlashi normal (§6.1a) — mijoz uchun bu spam.

**Fayl:** `core/logic/screenshots.py`, `register_batch`

### Bajarish

`BatchDecision.customer_text` ni faqat **birinchi** partiyada to'ldir.
`customer_text` beriladigan joyda (taxminan **168-qator**):

```python
            customer_text = await get_template(session, "SCREENSHOT_FOLLOWUP")
```

→

```python
            # §5.3 matni case boshiga BIR MARTA yuboriladi. Admin rasmni
            # qayta tashlashi normal holat (§6.1a) — lekin mijoz uchun
            # bir xil matnni qayta-qayta olish spam bo'ladi.
            oldingi_partiya_bor = await session.execute(
                select(ScreenshotBatch.id)
                .where(
                    ScreenshotBatch.case_id == case.id,
                    ScreenshotBatch.id != batch.id,
                )
                .limit(1)
            )
            customer_text = (
                None
                if oldingi_partiya_bor.scalars().first() is not None
                else await get_template(session, "SCREENSHOT_FOLLOWUP")
            )
```

### Test

- birinchi partiya → `customer_text` to'ldirilgan;
- o'sha case'ning ikkinchi partiyasi → `customer_text is None`;
- boshqa case'ning birinchi partiyasi → to'ldirilgan.

---

## T-16. `pytest` jonli log fayliga yozmasin

**Muammo:** `configure_logging("adminbot")` `adminbot_service/bot.py:158`
da **modul darajasida** chaqiriladi. Testlar bu modulni import qilganda
log sozlanadi va test uydirmalari jonli faylga tushadi.

Tekshirilgan: `pytest -q` dan oldin `logs/adminbot.log` = 180 834 bayt,
keyin = 189 391 bayt. Faylga tushgan:

```
2026-08-16 10:41:07 | INFO | manual_case | Yangi case C1: nomer 998901111111, tg_id=111.
2026-08-16 10:41:07 | INFO | screenshots | Partiya #1 qayd etildi: case=C1, admin=Aziz.
```

Baza ajratilgan ✅ — faqat log aralashadi, lekin haqiqiy xato
tekshirganda chalg'itadi.

### Bajarish — 3 ta faylda bir xil o'zgarish

| Fayl | Qator |
|---|---|
| `adminbot_service/bot.py` | 158 |
| `teleton_service/manual_relay.py` | 65 |
| `teleton_service/relay.py` | 30 |

Har birida `configure_logging(...)` chaqiruvini **modul darajasidan
`main()` ichiga ko'chir** — funksiyaning eng birinchi qatoriga.

Masalan `adminbot_service/bot.py`:

```python
# 158-qatordagi modul darajasidagi chaqiruvni O'CHIR:
# configure_logging("adminbot")

...

async def main() -> None:
    # Log sozlash modul darajasida emas, shu yerda: aks holda testlar
    # bu modulni import qilganda jonli `logs/adminbot.log` fayliga test
    # uydirmalari yozilib, haqiqiy xato izlashda chalg'itardi.
    configure_logging("adminbot")

    bot = Bot(...)
```

`log = logging.getLogger("...")` qatorlari **modul darajasida qolsin** —
ular fayl yaratmaydi.

### Test

```python
def test_import_does_not_create_log_file(tmp_path, monkeypatch):
    """Modul importi log faylini yaratmasligi kerak (testlar jonli
    logni ifloslantirmasin)."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    import importlib
    import adminbot_service.bot as b
    importlib.reload(b)
    assert not list(tmp_path.glob("*.log"))
```

---

# YAKUNIY TEKSHIRUV RO'YXATI

Hamma topshiriq bajarilgandan keyin:

```bash
python -m pytest -q
```

- [ ] Testlar soni **291 dan kam emas** (yangi testlar bilan ko'proq)
- [ ] Xizmatlar qayta ishga tushdi va `logs/teleton_v2.log` da
      `3 ta admin sessiyasi ulandi` yozuvi bor

**Qo'lda jonli tekshiruv (soya rejimi YOQILGAN holda):**

- [ ] `/shadow` → holat ko'rsatadi, **o'zgartirmaydi** (T-1)
- [ ] `/shadow off` → o'zgartiradi, `/shadow on` → qaytaradi (T-1)
- [ ] `/checkpatterns` → shablonlar ro'yxatini beradi, xabar
      **o'chirilmaydi** (T-3)
- [ ] `/check` reply bilan → avvalgidek ishlaydi (T-3 regressiya)
- [ ] Rasm partiyasi → nazorat guruhida **faqat** forward + caption,
      bot javoblari **yo'q** (T-4)
- [ ] Soya rejimida rasm tashlansa mijozga **hech narsa** yozilmaydi (T-2)
- [ ] Caption'da admin **ismi** va mijozga bosiladigan havola bor
      (T-12, T-13)
- [ ] Bitta case'ga 2 marta rasm → dublikat alerti **yo'q** (T-10)
- [ ] Natija chiqqanda case'ning **barcha** guruh postlariga reaksiya
      qo'yiladi (T-6)
- [ ] `/sessions` → 3 ta sessiya holati ko'rinadi (T-8)
- [ ] `ADMIN` rolidagi akkaunt `/stats` → `(faqat sizniki)` (T-7)
- [ ] Tekshiruvchiga ketgan so'rov soxta case/alert yaratmaydi (T-5)

**Jonli rejimga o'tishdan oldin (kod emas, sozlama):**

- [ ] `/checkpatterns` bilan uchala kategoriyani real javob
      variantlari bilan to'ldir — tekshiruvchi qanday yozsa,
      aynan shunday. `/testcheck <matn>` bilan har birini sinab ko'r.
- [ ] 1–2 kun soya rejimida ishlat, `/unrecognized` jurnalidan
      shablonlarni to'ldir (TZ §6.4.6 tavsiyasi).
- [ ] Shundan keyingina `/shadow off`.
