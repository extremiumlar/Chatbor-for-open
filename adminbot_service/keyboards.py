"""Tugmalar (klaviaturalar) — TZ 9.2/9.3.

Ikki xil tugma ishlatiladi:
- **ReplyKeyboard** (pastdagi doimiy menyu) — asosiy bo'limlarga o'tish uchun.
  Admin har safar buyruq yozmaydi, menyu doim ko'rinib turadi.
- **InlineKeyboard** (xabar ostidagi tugmalar) — ro'yxat elementini tanlash,
  amal bajarish, sahifalash uchun.

callback_data Telegram'da 64 baytdan oshmasligi kerak — shuning uchun
prefikslar qisqa (`bot:`, `tpl:`, `cs:`, `usr:`, `pg:`).
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from core.enums import CaseStatus, MANUAL_RESOLVABLE_STATUSES
from core.logic.templates import is_active
from core.logic.bot_pool import PHONE_FORMATS

# --------------------------------------------------------------------------- #
# Pastdagi doimiy menyu
# --------------------------------------------------------------------------- #

BTN_STATS = "📊 Statistika"
BTN_PROBLEMS = "⚠️ Muammolar"
BTN_BOTS = "🤖 Botlar"
BTN_PENDING = "⏳ Navbat"
BTN_TEMPLATES = "📝 Shablonlar"
BTN_SEARCH = "🔍 Nomer qidirish"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_HELP = "ℹ️ Yordam"

MAIN_MENU_BUTTONS = {
    BTN_STATS,
    BTN_PROBLEMS,
    BTN_BOTS,
    BTN_PENDING,
    BTN_TEMPLATES,
    BTN_SEARCH,
    BTN_SETTINGS,
    BTN_HELP,
}


def main_menu(admin=None) -> ReplyKeyboardMarkup:
    """Pastdagi doimiy menyu — rolga moslangan (TZ 14, Q43).

    `admin=None` bo'lsa to'liq menyu qaytadi (eski chaqiruvlar bilan
    moslik uchun). Rol berilsa, o'sha rolga yopiq bo'limlar ko'rsatilmaydi.

    Diqqat: bu faqat KO'RSATISH. Haqiqiy to'siq — `RolePermission`
    middleware; tugmani yashirish o'zi himoya emas (eski xabardagi tugma
    keyin ham bosilishi mumkin).
    """
    from core.logic import permissions as perms

    def ok(text: str) -> bool:
        return admin is None or perms.can_use_menu_button(admin, text)

    candidates = [
        [BTN_STATS, BTN_PROBLEMS],
        [BTN_BOTS, BTN_PENDING],
        [BTN_TEMPLATES, BTN_SEARCH],
        [BTN_SETTINGS, BTN_HELP],
    ]
    rows = []
    for row in candidates:
        visible = [KeyboardButton(text=t) for t in row if ok(t)]
        if visible:
            rows.append(visible)

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Menyudan tanlang yoki nomer yuboring",
    )


def cancel_only() -> InlineKeyboardMarkup:
    """Ko'p qadamli oqim (FSM) davomida — bekor qilish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Bekor qilish", callback_data="cancel")]]
    )


# --------------------------------------------------------------------------- #
# Botlar (TZ 3.3, 9.5)
# --------------------------------------------------------------------------- #


def bots_list(bots) -> InlineKeyboardMarkup:
    rows = []
    for bot in bots:
        holat = "🔴" if bot.is_busy else ("🟢" if bot.is_active else "⏸")
        rows.append(
            [InlineKeyboardButton(text=f"{holat} @{bot.username}", callback_data=f"bot:{bot.id}")]
        )
    rows.append([InlineKeyboardButton(text="➕ Yangi bot qo'shish", callback_data="bot:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_card(bot) -> InlineKeyboardMarkup:
    rows = []
    if bot.is_active:
        rows.append(
            [InlineKeyboardButton(text="⏸ Vaqtincha o'chirish", callback_data=f"bot:{bot.id}:off")]
        )
    else:
        rows.append([InlineKeyboardButton(text="▶️ Yoqish", callback_data=f"bot:{bot.id}:on")])

    rows.append(
        [InlineKeyboardButton(text="📱 Nomer formatini o'zgartirish", callback_data=f"bot:{bot.id}:fmt")]
    )
    if bot.is_busy:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Majburan bo'shatish", callback_data=f"bot:{bot.id}:free"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Botlar ro'yxati", callback_data="nav:bots")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bot_format_choice(bot_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=fmt, callback_data=f"bot:{bot_id}:fmt:{i}")]
        for i, fmt in enumerate(PHONE_FORMATS)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"bot:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_bot_format_choice() -> InlineKeyboardMarkup:
    """Yangi bot qo'shishda format tanlash (FSM ichida)."""
    rows = [
        [InlineKeyboardButton(text=fmt, callback_data=f"newbot:fmt:{i}")]
        for i, fmt in enumerate(PHONE_FORMATS)
    ]
    rows.append([InlineKeyboardButton(text="✖️ Bekor qilish", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_bot_start_choice() -> InlineKeyboardMarkup:
    """Q54 — bot avval /start talab qiladimi?"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Yo'q, kerak emas", callback_data="newbot:start:0")],
            [InlineKeyboardButton(text="Ha, avval /start yuborilsin", callback_data="newbot:start:1")],
            [InlineKeyboardButton(text="✖️ Bekor qilish", callback_data="cancel")],
        ]
    )


# --------------------------------------------------------------------------- #
# Shablonlar (TZ 7.1 / 7.2 — ikki xil to'plam ALOHIDA, Q47)
# --------------------------------------------------------------------------- #


def templates_root() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Mijozga yuboriladigan", callback_data="nav:tpl_customer")],
            [InlineKeyboardButton(text="🤖 Bot javobini tanish", callback_data="nav:tpl_bot")],
        ]
    )


def template_keys(keys, kind: str) -> InlineKeyboardMarkup:
    """kind: 'c' = mijozga yuboriladigan, 'b' = bot-tanish.

    Mijoz shablonlarida ISHLAYDIGANLARI yuqorida, v1 merosi esa ajratgich
    ostida ko'rsatiladi — aks holda admin o'lik shablonni tahrirlab, matnim
    nega chiqmayapti deb ovora bo'ladi (jonli sinovda shunday bo'lgan).
    """
    if kind != "c":
        rows = [
            [InlineKeyboardButton(text=key, callback_data=f"tpl:{kind}:{key}")]
            for key in keys
        ]
        rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="nav:templates")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    keys = list(keys)
    active = [k for k in keys if is_active(k)]
    legacy = [k for k in keys if not is_active(k)]

    rows = [
        [InlineKeyboardButton(text=f"✅ {key}", callback_data=f"tpl:{kind}:{key}")]
        for key in active
    ]
    if legacy:
        rows.append([InlineKeyboardButton(text="— — ishlatilmaydi — —", callback_data="noop")])
        rows += [
            [InlineKeyboardButton(text=f"💤 {key}", callback_data=f"tpl:{kind}:{key}")]
            for key in legacy
        ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="nav:templates")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def template_card(kind: str, key: str) -> InlineKeyboardMarkup:
    back = "nav:tpl_customer" if kind == "c" else "nav:tpl_bot"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"tpl:{kind}:{key}:edit")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)],
        ]
    )


# --------------------------------------------------------------------------- #
# Case ro'yxati / kartochkasi (TZ 9.3)
# --------------------------------------------------------------------------- #

PAGE_SIZE = 8


def case_list(cases, kind: str, page: int, total: int, extra: str = "") -> InlineKeyboardMarkup:
    """kind: 'pr' = muammolar, 'pn' = navbat, 'sr' = qidiruv natijalari.

    Audit J-6 — `extra` (masalan qidiruv nomeri) berilsa, sahifalash
    tugmalari `pg:{kind}:{extra}:{page}` shaklida bo'ladi — shu orqali
    "sr" (qidiruv) sahifalash o'ziga xos filtrni (nomerni) saqlab qoladi,
    "pr"/"pn" ro'yxatlari bilan aralashib ketmaydi.

    Audit O-3 — har bir case tugmasi endi manba (`kind`/`page`/`extra`)ni
    o'zi bilan olib yuradi (`cs:{id}:{kind}:{page}` yoki qidiruv uchun
    `cs:{id}:sr:{extra}:{page}`), shuning uchun kartochkadagi "⬅️ Orqaga"
    tugmasi HAQIQATAN qayerdan kelingan bo'lsa o'sha ro'yxat/sahifaga
    qaytaradi — avval doim "Muammolar" ro'yxatiga qaytarardi.
    """
    if kind == "sr":
        origin_suffix = f":{kind}:{extra}:{page}"
    else:
        origin_suffix = f":{kind}:{page}"
    rows = [
        [
            InlineKeyboardButton(
                text=f"#{c.id} · {c.phone} · {c.status.value}",
                callback_data=f"cs:{c.id}{origin_suffix}",
            )
        ]
        for c in cases
    ]

    last_page = max(0, (total - 1) // PAGE_SIZE)
    if last_page > 0:
        prefix = f"pg:{kind}:{extra}:" if extra else f"pg:{kind}:"
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}{page - 1}"))
        nav.append(
            InlineKeyboardButton(text=f"{page + 1}/{last_page + 1}", callback_data="noop")
        )
        if page < last_page:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}{page + 1}"))
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def case_card(case, user, back: str = "nav:problems") -> InlineKeyboardMarkup:
    rows = []

    # TZ 9.3 — "Noaniq natijada: [Tasdiqlash] [Rad] [Qayta uzatish]"
    # Audit K-3 — shu ro'yxat core.logic.case_admin'dagi server-tomon
    # tekshiruvi bilan BITTA manbadan (core.enums.MANUAL_RESOLVABLE_STATUSES)
    # olinadi, aks holda tugma ko'rinishi va server ruxsati mos kelmay qolishi
    # mumkin edi.
    if case.status in MANUAL_RESOLVABLE_STATUSES:
        rows.append(
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"cs:{case.id}:ok"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"cs:{case.id}:no"),
            ]
        )
        rows.append(
            [InlineKeyboardButton(text="🔄 Qayta uzatish", callback_data=f"cs:{case.id}:again")]
        )

    # TZ 5.2 — shubhali holat
    if case.status == CaseStatus.SUSPICIOUS_HOLD:
        rows.append(
            [
                InlineKeyboardButton(text="✅ Xavfsiz", callback_data=f"safe:{case.id}"),
                InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"block:{case.id}"),
            ]
        )

    if user is not None:
        rows.append(
            [InlineKeyboardButton(text="👤 Mijoz kartochkasi", callback_data=f"usr:{user.id}")]
        )
        chat_url = (
            f"https://t.me/{user.tg_username}"
            if user.tg_username
            else f"tg://user?id={user.tg_user_id}"
        )
        rows.append([InlineKeyboardButton(text="💬 Lichkaga o'tish", url=chat_url)])

    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# Mijoz kartochkasi (TZ 11.1 — CRM)
# --------------------------------------------------------------------------- #


def user_card(user, can_assign: bool = True, viewer_admin_id: int | None = None) -> InlineKeyboardMarkup:
    """Audit K-4 (TZ 11.0/11.1, Q51) — `can_assign` (Owner/Rop) va
    `viewer_admin_id` mijozni biriktirish/bekor qilish tugmalarini
    boshqaradi."""
    rows = []
    if user.is_blocked:
        rows.append(
            [InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"usr:{user.id}:unblock")]
        )
    else:
        rows.append([InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"usr:{user.id}:block")])

    if not user.is_safe:
        rows.append(
            [InlineKeyboardButton(text="✅ Xavfsiz deb belgilash", callback_data=f"usr:{user.id}:safe")]
        )

    if user.assigned_admin_id is None:
        rows.append(
            [InlineKeyboardButton(text="🎯 Menga biriktirish", callback_data=f"usr:{user.id}:claim")]
        )
    else:
        if user.assigned_admin_id == viewer_admin_id:
            rows.append([InlineKeyboardButton(text="✅ Sizga biriktirilgan", callback_data="noop")])
        if can_assign:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="♻️ Biriktirishni bekor qilish", callback_data=f"usr:{user.id}:unassign"
                    )
                ]
            )

    rows.append([InlineKeyboardButton(text="📝 Izoh yozish", callback_data=f"usr:{user.id}:note")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="nav:problems")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# Sozlamalar (TZ 9.1, 11.5)
# --------------------------------------------------------------------------- #


def settings_menu(verbose: bool) -> InlineKeyboardMarkup:
    mode = "batafsil (hammasi)" if verbose else "oddiy (faqat muhim)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔔 Bildirishnoma: {mode}", callback_data="nav:notify")],
            # Audit J-9 (TZ 2.2, 4.1) — avval bular faqat .env orqali sozlanardi.
            [InlineKeyboardButton(text="📱 Operator kodlari", callback_data="nav:opcodes")],
            [InlineKeyboardButton(text="⏱ Kupon kutish vaqti", callback_data="nav:timeout")],
            [InlineKeyboardButton(text="📋 Audit (admin harakatlari)", callback_data="nav:audit")],
            [InlineKeyboardButton(text="🔧 Tizim holati", callback_data="nav:health")],
            # TZ v2 4.3 — admin lichkalarining Telethon sessiya holati.
            [InlineKeyboardButton(text="🔌 Sessiyalar", callback_data="nav:sessions")],
        ]
    )


def opcodes_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="opcodes:edit")],
            [InlineKeyboardButton(text="⬅️ Sozlamalar", callback_data="nav:settings")],
        ]
    )


def timeout_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="timeout:edit")],
            [InlineKeyboardButton(text="⬅️ Sozlamalar", callback_data="nav:settings")],
        ]
    )


def notify_choice(verbose: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if not verbose else "") + "Oddiy (faqat muhim)",
                    callback_data="notify:off",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("✅ " if verbose else "") + "Batafsil (hammasi)",
                    callback_data="notify:on",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Sozlamalar", callback_data="nav:settings")],
        ]
    )


def back_to(target: str, text: str = "⬅️ Orqaga") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=target)]]
    )
