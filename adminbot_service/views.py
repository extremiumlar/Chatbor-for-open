"""Xabar matnlari (kartochkalar) — tugmali interfeys uchun ko'rinishlar.

Handler'lar faqat ma'lumot yig'adi, matn yasashni shu modul bajaradi.
"""

from core.enums import CaseStatus
from core.logic.admins import display_name
from core.logic.screenshots import to_tashkent

_STATUS_LABEL = {
    CaseStatus.NUMBER_RECEIVED: "⏳ Navbatda (bot kutilmoqda)",
    CaseStatus.SENT_TO_BOT: "📤 Botga yuborildi",
    CaseStatus.AWAITING_COUPON: "⌛ Mijozdan kupon kutilmoqda",
    CaseStatus.COUPON_SENT_TO_BOT: "📤 Kupon botga yuborildi",
    CaseStatus.CONFIRMED: "✅ Tasdiqlandi",
    CaseStatus.REJECTED: "❌ Rad etildi",
    CaseStatus.EXPIRED: "⛔ Kupon muddati o'tgan",
    CaseStatus.SUSPICIOUS_HOLD: "🕵️ Shubhali — admin tekshiruvi kutilmoqda",
    CaseStatus.NEEDS_ADMIN: "🛠 Admin aralashuvi kerak",
    CaseStatus.TIMEOUT: "⏱ Bot javob bermadi",
    CaseStatus.CUSTOMER_TIMEOUT: "⏱ Mijoz kupon yubormadi",
    CaseStatus.EXPIRED_SESSION: "🗑 Seans tashlab ketilgan",
    CaseStatus.DUPLICATE_ACTIVE: "♻️ Ikkinchi nomer (oldingisi tugamagan)",
    CaseStatus.ALREADY_CONFIRMED: "✅ Allaqachon tasdiqlangan",
}


def status_label(status: CaseStatus) -> str:
    return _STATUS_LABEL.get(status, status.value)


def welcome(name: str | None) -> str:
    return (
        f"Assalomu alaykum{', ' + name if name else ''}!\n\n"
        "Bu — kupon tekshirish tizimining boshqaruv paneli. Pastdagi menyudan "
        "kerakli bo'limni tanlang.\n\n"
        "Nomer bo'yicha tez qidirish uchun shunchaki nomerni yuborishingiz ham mumkin."
    )


def help_for_role(admin, in_group: bool = False) -> str:
    """Rolga mos buyruqlar ro'yxati — TZ 14 (Q43: "har biri o'z roliga mos
    ko'rinishni ko'radi").

    Ro'yxat `core.logic.permissions` jadvalidan tuziladi — ya'ni bu yerda
    ko'rinadigan narsa aynan bajarilishi mumkin bo'lgan narsa. Ikkovi bitta
    manbadan olinadi, shuning uchun "ko'rinadi-yu ishlamaydi" holati bo'lmaydi.
    """
    from core.logic import permissions as perms

    allowed = perms.allowed_commands(admin)
    by_section: dict[str, list] = {}
    for p in allowed:
        by_section.setdefault(p.section, []).append(p)

    lines = [
        f"ℹ️ <b>Sizga ochiq buyruqlar</b> — {len(allowed)} ta",
        "",
        f"Rolingiz: {perms.role_label(admin.role)}",
        "",
    ]
    for section in perms.SECTION_ORDER:
        items = by_section.get(section)
        if not items:
            continue
        lines.append(f"<b>{section}</b>")
        for p in items:
            lines.append(f"  {p.label} — {p.hint}" if p.hint else f"  {p.label}")
        lines.append("")

    if in_group:
        lines.append(
            "<i>Guruhda ham shu buyruqlar ishlaydi. Har kim o'z roliga mos "
            "ro'yxatni ko'radi — bu ro'yxat aynan sizniki.</i>"
        )
    else:
        lines.append(
            "<i>Pastdagi menyu ham rolingizga moslangan. Ro'yxatda yo'q "
            "buyruqni yuborsangiz, tizim rad javobini beradi.</i>"
        )
    return "\n".join(lines)


HELP_TEXT = (
    "ℹ️ <b>Bo'limlar</b>\n\n"
    "📊 <b>Statistika</b> — bugungi murojaatlar, holatlar bo'yicha sonlar.\n"
    "⚠️ <b>Muammolar</b> — admin e'tibori kerak bo'lgan murojaatlar. Har birini "
    "bosib tasdiqlash / rad etish / qayta uzatish mumkin.\n"
    "🤖 <b>Botlar</b> — tekshiruv botlari holati; yoqish/o'chirish, nomer "
    "formatini o'zgartirish, yangi bot qo'shish.\n"
    "⏳ <b>Navbat</b> — bo'sh bot kutib turgan murojaatlar.\n"
    "📝 <b>Shablonlar</b> — mijozga yuboriladigan matnlar va bot javobini "
    "tanish namunalari (ikkovi alohida!).\n"
    "🔍 <b>Nomer qidirish</b> — nomer bo'yicha butun tarix.\n"
    "⚙️ <b>Sozlamalar</b> — bildirishnoma rejimi, audit, tizim holati.\n\n"
    "<i>Eski buyruqlar ham ishlaydi:</i> /bots, /stats, /problems, /pending, "
    "/templates, /audit, <code>drop find &lt;nomer&gt;</code> va boshqalar.\n\n"
    "🆕 <b>v2 (qo'lda oqim):</b>\n"
    "/setgroup — nazorat guruhini belgilash (guruh ichida yozing yoki "
    "<code>/setgroup &lt;chat_id&gt;</code>)\n"
    "/setchecker — tekshiruvchi lichkani belgilash\n"
    "/checkpatterns, /addcheckpattern, /delcheckpattern — javob tanish "
    "shablonlari\n"
    "/testcheck &lt;matn&gt; — javob qanday tanilishini sinash\n"
    "/unrecognized — tanilmagan javoblar jurnali (tugma bilan shablonga "
    "qo'shish)\n"
    "/shadow — soya rejimi (standart: yoqilgan — mijozga hech narsa yozilmaydi)\n"
    "/vstats — v2 statistika (Bugun/Hafta/Oy; oddiy admin faqat o'zinikini "
    "ko'radi). Kunlik hisobot guruhga avtomatik tushadi\n"
    "/setreporttime HH:MM — kunlik hisobot vaqtini o'zgartirish (Toshkent)\n"
    "/uyqu off|on [daqiqa] — bot ishlab turgan kompyuterning uyqu rejimi "
    "(sinov davrida; faqat Windows)"
)


def bot_line(bot) -> str:
    if bot.is_busy:
        holat = "🔴 band"
    elif not bot.is_active:
        holat = "⏸ o'chirilgan"
    else:
        holat = "🟢 bo'sh"
    return f"{holat} · @{bot.username}"


def bot_card(bot) -> str:
    if bot.is_busy:
        holat = "🔴 band"
    elif not bot.is_active:
        holat = "⏸ vaqtincha o'chirilgan"
    else:
        holat = "🟢 bo'sh"

    lines = [
        f"🤖 <b>@{bot.username}</b>  (#{bot.id})",
        "",
        f"Holat: {holat}",
        f"Nomer formati: <code>{bot.phone_format}</code>",
        f"Jami ishlangan case: {bot.total_processed}",
        f"Joriy case: {bot.current_case_id or '—'}",
        f"Oxirgi ishlatilgan: {bot.last_used_at or '—'}",
    ]
    if bot.needs_start_greeting:
        lines.append("Birinchi ishlatishda <code>/start</code> yuboriladi (Q54)")
    if bot.owner_admin_id is not None:
        lines.append(f"Faqat admin #{bot.owner_admin_id} uchun (Q55)")
    return "\n".join(lines)


def bots_summary(bots) -> str:
    if not bots:
        return (
            "🤖 <b>Tekshiruv botlari</b>\n\n"
            "Hali birorta bot qo'shilmagan. Pastdagi tugma bilan qo'shing."
        )
    free = sum(1 for b in bots if b.is_active and not b.is_busy)
    busy = sum(1 for b in bots if b.is_busy)
    off = sum(1 for b in bots if not b.is_active)
    return (
        f"🤖 <b>Tekshiruv botlari</b> — {len(bots)} ta\n"
        f"🟢 bo'sh: {free}   🔴 band: {busy}   ⏸ o'chirilgan: {off}\n\n"
        "Har bir bot bir vaqtda faqat BITTA murojaatni yuritadi (TZ 3-bo'lim) — "
        "ya'ni bo'sh botlar soni = parallel xizmat ko'rsatish imkoniyati.\n\n"
        "Tafsilot va boshqarish uchun botni tanlang:"
    )


def stats_text(stats, own_only: bool = False) -> str:
    if stats.by_status:
        rows = "\n".join(
            f"  {status_label(CaseStatus(s))}: <b>{c}</b>" for s, c in stats.by_status.items()
        )
    else:
        rows = "  (hali murojaat yo'q)"
    sarlavha = "📊 <b>Statistika</b>"
    if own_only:
        # §8.4 — oddiy admin faqat o'zinikini ko'radi; buni yashirmaymiz,
        # aks holda son "butun tizim" deb noto'g'ri o'qiladi.
        sarlavha += " <i>(faqat sizniki)</i>"
    return (
        f"{sarlavha}\n\n"
        f"Bugungi murojaatlar: <b>{stats.today_count}</b>\n"
        f"Ochiq muammoli holatlar: <b>{stats.problem_count}</b>\n\n"
        f"Holat bo'yicha (barcha vaqt):\n{rows}\n\n"
        "<i>Admin kesimidagi batafsil ko'rsatkichlar uchun /vstats.</i>"
    )


def case_card(case, user, attempts) -> str:
    lines = [
        f"📋 <b>Murojaat #{case.id}</b>",
        "",
        f"Nomer: <code>{case.phone}</code>",
        f"Holat: {status_label(case.status)}",
        f"Yaratildi: {case.created_at}",
    ]
    if case.confirmed_at:
        lines.append(f"Tasdiqlandi: {case.confirmed_at}")
    lines.append(f"Bot: {case.bot_id or '—'}")
    if case.expired_attempts:
        lines.append(f"Muddati o'tgan urinishlar: {case.expired_attempts}/5")
    if case.admin_redispatch_requested:
        lines.append("🔄 <i>Qayta uzatish so'ralgan — Teleton tez orada bajaradi.</i>")

    if user is not None:
        uname = f"@{user.tg_username}" if user.tg_username else "—"
        flags = []
        if user.is_blocked:
            flags.append("🚫 bloklangan")
        if not user.is_safe:
            flags.append("🕵️ shubhali")
        lines += [
            "",
            f"👤 Mijoz: {user.display_name or '—'} ({uname})",
            f"Telegram ID: <code>{user.tg_user_id}</code>",
        ]
        if flags:
            lines.append("Belgilar: " + ", ".join(flags))
        if user.note:
            lines.append(f"📝 Izoh: {user.note}")

    lines.append("")
    if attempts:
        lines.append("<b>Kupon urinishlari:</b>")
        for a in attempts:
            lines.append(f"  <code>{a.coupon}</code> → {status_label(a.result)} ({a.created_at})")
    else:
        lines.append("<i>Kupon urinishi yo'q.</i>")

    return "\n".join(lines)


def user_card(user, cases) -> str:
    uname = f"@{user.tg_username}" if user.tg_username else "—"
    biriktirilgan = (
        f"admin #{user.assigned_admin_id}" if user.assigned_admin_id is not None else "hech kimga (ochiq)"
    )
    lines = [
        f"👤 <b>{user.display_name or 'Mijoz'}</b>  (#{user.id})",
        "",
        f"Username: {uname}",
        f"Telegram ID: <code>{user.tg_user_id}</code>",
        f"Oxirgi nomer: <code>{user.phone or '—'}</code>",
        f"Holat: {'🚫 bloklangan' if user.is_blocked else ('🕵️ shubhali' if not user.is_safe else '✅ xavfsiz')}",
        f"Biriktirilgan: {biriktirilgan}",  # TZ 11.0/11.1, Q51 — audit K-4
        f"Birinchi ko'rilgan: {user.first_seen}",
        f"Oxirgi ko'rilgan: {user.last_seen}",
        f"📝 Izoh: {user.note or '—'}",
        "",
        f"<b>Murojaatlar ({len(cases)}):</b>",
    ]
    for c in cases[:15]:
        lines.append(f"  #{c.id} · <code>{c.phone}</code> · {status_label(c.status)}")
    if len(cases) > 15:
        lines.append(f"  <i>... va yana {len(cases) - 15} ta</i>")
    return "\n".join(lines)


def case_list_text(kind: str, total: int) -> str:
    if kind == "pr":
        if total == 0:
            return "⚠️ <b>Muammolar</b>\n\nHozircha admin e'tiborini talab qiladigan murojaat yo'q. ✅"
        return (
            f"⚠️ <b>Muammolar</b> — {total} ta\n\n"
            "Bu murojaatlar avtomatik hal bo'lmadi. Har birini bosib ko'rib chiqing:"
        )
    if total == 0:
        return "⏳ <b>Navbat</b>\n\nNavbatda hech kim yo'q — barcha botlar yetarli. ✅"
    return (
        f"⏳ <b>Navbat</b> — {total} ta\n\n"
        "Bu murojaatlar bo'sh bot kutmoqda (hamma bot band). Tafsilot uchun tanlang:"
    )


def audit_text(entries) -> str:
    if not entries:
        return "📋 <b>Audit</b>\n\nHali hech qanday admin harakati qayd etilmagan."
    lines = ["📋 <b>So'nggi admin harakatlari</b>", ""]
    for e in entries:
        lines.append(f"<code>{e.created_at}</code>\n  admin {e.admin_tg_id} → <b>{e.action}</b>")
        if e.details:
            lines.append(f"  {e.details}")
    return "\n".join(lines)


def health_text(bots, missing_patterns_list, use_real_bots: bool, shadow: bool | None = None) -> str:
    total = len(bots)
    free = sum(1 for b in bots if b.is_active and not b.is_busy)
    lines = [
        "🔧 <b>Tizim holati</b>",
        "",
        f"Tekshiruv botlari: {total} ta (bo'sh: {free})",
        f"Rejim: {'REAL botlar' if use_real_bots else 'MOCK (soxta) bot — sinov rejimi'}",
    ]
    # T-9 — soya rejimi endi shu yerda ham ko'rinadi. `/shadow` buyrug'i
    # texnik sozlash bo'lgani uchun oddiy adminga yopiq, lekin soya rejimida
    # mijozga HECH NARSA yozilmaydi — buni bilmagan operator tizimni buzilgan
    # deb o'ylaydi. Ko'rish hammaga, o'zgartirish esa faqat Owner/Dasturchiga.
    if shadow is not None:
        lines.append(
            "🕶 Soya rejimi: <b>YOQILGAN</b> — mijozlarga hech narsa yozilmaydi"
            if shadow
            else "🟢 Soya rejimi: o'chirilgan — natijalar mijozlarga yuboriladi"
        )
    if use_real_bots:
        if missing_patterns_list:
            lines.append(
                "❗ Bot-tanish shablonlari to'liq emas: " + ", ".join(missing_patterns_list)
            )
        else:
            lines.append("✅ Bot-tanish shablonlari to'liq kiritilgan.")
    else:
        lines.append(
            "<i>Mock rejimda bot-tanish shablonlari ishlatilmaydi — javoblarni "
            "soxta bot beradi (111111 → tasdiq, 222222 → muddati o'tgan, "
            "333333 → rad).</i>"
        )
    if total == 1:
        lines += [
            "",
            "⚠️ Faqat 1 ta bot bor — bir vaqtda faqat bitta mijoz xizmat oladi, "
            "qolganlar navbatga tushadi. Parallel ishlash uchun turli bot "
            "qo'shing.",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Sessiyalar — TZ v2 4.3
# --------------------------------------------------------------------------- #

_SESSION_BELGI = {
    "CONNECTED": "🟢",
    "DISCONNECTED": "🟡",
    "AUTH_LOST": "🔴",
}

SESSIONS_EMPTY_TEXT = (
    "🔌 <b>Admin sessiyalari</b>\n\n"
    "Hech qanday admin sessiyasi ulanmagan — hozir birorta admin lichkasi "
    "kuzatilmayapti.\n\n"
    "Qo'shish (serverda): <code>python -m scripts.add_admin_session</code>"
)


def sessions_text(rows) -> str:
    """TZ v2 4.3 — har akkaunt holati va oxirgi faollik vaqti.

    Nega alohida ekran kerak: sessiya o'lganda o'sha adminning mijozlari
    JIMGINA yo'qoladi — hech qanday case ochilmaydi, demak "navbat bo'sh"
    ko'rinadi. Alert bir marta keladi va ko'zdan qochishi mumkin, shuning
    uchun istalgan payt qarab tekshirish imkoni bo'lishi shart.
    """
    lines = ["🔌 <b>Admin sessiyalari</b> (TZ 4.3)", ""]
    auth_lost = 0
    for sess, admin in rows:
        belgi = _SESSION_BELGI.get(sess.status.value, "⚪️")
        if sess.status.value == "AUTH_LOST":
            auth_lost += 1
        lines.append(f"{belgi} <b>{display_name(admin)}</b>")
        lines.append(f"    {sess.phone or '—'} · <code>{sess.session_name}</code>")
        lines.append(f"    Holat: {sess.status.value}")
        if sess.last_seen_at:
            lines.append(
                f"    Oxirgi faollik: {to_tashkent(sess.last_seen_at):%H:%M · %d.%m.%Y}"
            )
        else:
            lines.append("    Oxirgi faollik: — (hali bir marta ham ulanmagan)")
        if not admin.is_active:
            # Nofaol admin sessiyasi ATAYLAB ko'tarilmaydi (TZ v2 4.2b) —
            # buni yozmasak, "nega uzilgan?" deb bekorga qidiriladi.
            lines.append("    ⏸ Admin nofaol — sessiya ataylab ko'tarilmagan")
        if sess.last_error:
            lines.append(f"    ⚠️ {sess.last_error[:120]}")
        lines.append("")

    if auth_lost:
        lines.append(
            f"🔴 <b>{auth_lost} ta sessiyada avtorizatsiya yo'qolgan</b> — qayta "
            "login shart, aks holda o'sha adminlarning mijozlari umuman "
            "ko'rinmaydi:\n<code>python -m scripts.add_admin_session</code>"
        )
    else:
        lines.append(
            "<i>🟢 ulangan · 🟡 uzilgan (qayta ulanishga urinadi) · "
            "🔴 avtorizatsiya yo'qolgan (qayta login shart)</i>"
        )
    return "\n".join(lines)
