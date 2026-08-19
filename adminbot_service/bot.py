"""Adminbot (aiogram 3.x) — TZ 9-bo'lim, TUGMALI interfeys.

Interfeys tamoyili: admin hech qanday buyruq sintaksisini eslab qolmasligi
kerak. Pastda doimiy menyu (ReplyKeyboard), ro'yxatlar va amallar xabar
ostidagi tugmalar (InlineKeyboard) orqali. Qiymat kiritish kerak bo'lganda
bot o'zi so'raydi (FSM), admin faqat javob yozadi.

Eski slash-buyruqlar ham SAQLANGAN (TZ 9.2 ularni buyruq sifatida sanaydi,
va tezkor ishlatish uchun qulay) — lekin asosiy yo'l endi tugmalar.

Qamrov (hech qanday funksiya yo'qotilmagan + TZ'da bor-u avval qurilmagani
qo'shilgan):
- Botlar: ro'yxat/holat, yoqish/o'chirish (3.3), format o'zgartirish (9.5),
  majburan bo'shatish (12), yangi bot qo'shish (3.3, Q54)
- Shablonlar: mijozga yuboriladigan (7.2) va bot-tanish (7.1) — ALOHIDA (Q47)
- Muammolar/navbat: sahifalangan ro'yxat, case kartochkasi, va TZ 9.3 amallari
  (Tasdiqlash / Rad etish / Qayta uzatish)
- Shubhali holat: Xavfsiz / Bloklash (5.2) — notifier alertlaridagi tugmalar
  ham shu handler'larga tushadi
- Mijoz kartochkasi: bloklash/blokdan chiqarish, izoh (11.1)
- Statistika (10), Audit (11.5/12.2), bildirishnoma rejimi (9.1), tizim holati
- Nomer bo'yicha qidiruv (9.2 `drop find`)

Audit K-4/J-8 — rol tizimi (owner/rop/dasturchi/admin/kuzatuvchi, TZ
14-bo'lim) va TZ 11.0 (Q51 — TASDIQLANGAN) ko'rish-cheklovi endi mavjud:
Owner/Rop hammasini ko'radi, qolgan rollar faqat o'ziga biriktirilgan (yoki
hali hech kimga biriktirilmagan) mijoz/case'larni ko'radi. Biriktirish
"🎯 Menga biriktirish" tugmasi (yoki Owner/Rop uchun boshqa adminga
biriktirish) orqali, mijoz kartochkasida.
"""

import asyncio
import datetime
import json
import logging

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from sqlalchemy import select

from adminbot_service import keyboards as kb
from adminbot_service import views
from adminbot_service.states import (
    AddBotFlow,
    EditOperatorCodesFlow,
    EditPatternFlow,
    EditTemplateFlow,
    EditTimeoutFlow,
    SearchFlow,
    UserNoteFlow,
)
from core.config import settings
from core.db import get_session, init_db
from core.enums import PROBLEM_STATUSES, CaseStatus
from core.logic.admins import (
    can_see_everything,
    display_name,
    ensure_admins_seeded,
    get_admin_by_tg_id,
    is_last_active_owner,
    list_admin_sessions,
    list_admins,
    refresh_admin_identity,
    set_admin_role,
)
from core.logic.audit import list_recent, log_action
from core.logic.bot_patterns import (
    REQUIRED_KEYS as BOT_PATTERN_KEYS,
    list_patterns as list_bot_patterns,
    missing_patterns,
    set_pattern as set_bot_pattern,
)
from core.logic.bot_pool import (
    PHONE_FORMATS,
    add_bot,
    get_bot,
    list_bots,
    request_bot_force_release,
    set_bot_active,
    set_bot_phone_format,
)
from core.logic.case_admin import (
    InvalidCaseStateError,
    assign_customer,
    get_case_bundle,
    list_cases_by_statuses,
    manual_confirm,
    manual_reject,
    request_redispatch,
    set_user_blocked,
    set_user_note,
    set_user_safe,
)
from core.logic.case_search import search_cases
from core.logic.customers import cases_for_user
from core.logic.logging_setup import configure_logging
from core.logic import permissions as perms
from core.logic.phone import extract_phone
from core.logic.check_patterns import (
    AmbiguousMatch,
    CheckCategory,
    add_pattern,
    classify,
    get_all_patterns,
    missing_categories,
    remove_pattern,
)
from core.logic.settings_store import (
    get_checker_account,
    get_customer_timeout_seconds,
    get_daily_report_time,
    get_group_chat_id,
    get_operator_codes,
    is_shadow_mode,
    is_verbose,
    set_checker_account,
    set_customer_timeout_seconds,
    set_daily_report_time,
    set_group_chat_id,
    set_operator_codes,
    set_shadow_mode,
    set_verbose,
)
from core.logic.stats import gather_stats
from core.logic.v2_stats import (
    AdminStatRow,
    gather_v2_stats,
    gather_with_comparison,
    next_daily_report_due_utc,
    render_admin_detail,
    render_comparison,
    render_leaderboard,
    render_stats,
    tashkent_day_start_utc,
)
from core.logic.templates import DEFAULTS, ensure_templates_seeded, get_template, list_templates, set_template
from core.models import (
    Admin,
    AdminRole,
    Case,
    CheckRequest,
    CheckResult,
    JobKind,
    ScheduledJob,
    User,
)

# DIQQAT: `configure_logging` bu yerda EMAS, `main()` ichida chaqiriladi —
# T-16 ga qarang. Modul darajasida chaqirilsa, testlar shu modulni import
# qilishi bilanoq jonli `logs/adminbot.log` fayliga test uydirmalari
# yozilib, haqiqiy xato izlashda chalg'itardi.
log = logging.getLogger("adminbot")


# Guruh ichida ATAYLAB ishlaydigan buyruqlar (qolganlari faqat lichkada —
# aks holda nazorat guruhi "Tushunmadim" javoblari bilan to'lib ketadi).
GROUP_ALLOWED_COMMANDS = frozenset({"setgroup", "help"})


def should_handle_in_chat(chat_type: str, text: str | None) -> bool:
    """Bot shu chatdagi shu xabarga umuman javob berishi kerakmi.

    Lichkada — har doim (keyin oddiy handler'lar hal qiladi). Guruhda esa
    FAQAT `GROUP_ALLOWED_COMMANDS` dagi buyruqlarga. Avval bunday cheklov
    yo'q edi: nazorat guruhiga forward qilingan rasmlar va caption (ichida
    nomer bor) botni ishga tushirib, arxiv guruhini "Tushunmadim" va
    qidiruv natijalari bilan to'ldirardi — jonli sinovda har rasm
    partiyasidan keyin 3 ta chiqindi xabar, kuniga ~140 ta
    (TZ v2 5.2 — guruh toza arxiv bo'lishi kerak).
    """
    if chat_type not in ("group", "supergroup"):
        return True
    body = (text or "").strip()
    if not body.startswith("/"):
        return False
    command = body[1:].split(maxsplit=1)[0].split("@")[0].lower()
    return command in GROUP_ALLOWED_COMMANDS


class IsAdmin(BaseFilter):
    """TZ 12.2 — faqat `admins` jadvalidagi Telegram ID-lar buyruq bera oladi.

    Audit K-4 — topilsa `Admin` qatorining o'zini ("current_admin" nomi
    bilan) handler kwarg'iga in'ektsiya qiladi (aiogram 3 filtrlarning
    dict qaytarish imkoniyati) — har bir handler o'zi qayta so'rov
    qilmasdan joriy adminning id/rolini olishi uchun.
    """

    async def __call__(self, message: Message) -> bool | dict:
        if message.from_user is None:
            return False

        # Guruhda bot faqat ataylab guruh uchun mo'ljallangan buyruqlarga
        # javob beradi (`should_handle_in_chat` izohiga qarang).
        if not should_handle_in_chat(message.chat.type, message.text):
            return False

        async with get_session() as session:
            admin = await get_admin_by_tg_id(session, message.from_user.id)
            if admin is None:
                return False
            # `/setactive` bilan o'chirilgan admin botdan ham uzilishi kerak.
            # Avval bu tekshirilmasdi — o'chirilgan odam hamma buyruqni bemalol
            # ishlatishda davom etardi.
            if not admin.is_active:
                return False
            # Kim kimligi ro'yxatlarda tushunarli bo'lishi uchun ism/username
            # har muloqotda Telegram'dan yangilanadi (o'zgargan bo'lsagina
            # yoziladi) — aks holda adminlar raqam bo'lib ko'rinaverardi.
            u = message.from_user
            full = " ".join(p for p in (u.first_name, u.last_name) if p) or None
            await refresh_admin_identity(session, admin, full, u.username)
        return {"current_admin": admin}


admin_router = Router(name="admin")
admin_router.message.filter(IsAdmin())

fallback_router = Router(name="fallback")


class ResetStateOnMenuPress(BaseMiddleware):
    """Menyu tugmasi bosilsa yarim qolgan ko'p qadamli oqimni bekor qiladi.

    Aks holda: admin "Yangi bot qo'shish"ni boshlab, o'rtada "📊 Statistika"ni
    bossa, FSM holati saqlanib qolardi va keyingi yozgan matni "bot username'i"
    deb qabul qilinardi.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text in kb.MAIN_MENU_BUTTONS:
            state: FSMContext | None = data.get("state")
            if state is not None:
                await state.clear()
        return await handler(event, data)


admin_router.message.outer_middleware(ResetStateOnMenuPress())


class RolePermission(BaseMiddleware):
    """TZ 14 — rolga to'g'ri kelmaydigan buyruq/tugma BAJARILMAYDI.

    Nega middleware, nega har bir handler ichida emas: 26 buyruq va o'nlab
    tugma bor — har biriga qo'lda tekshiruv yozilsa, bittasi esdan chiqadi va
    jimgina teshik qoladi. Bu yerda esa hammasi bitta joydan o'tadi.

    Nega tugmani yashirish yetarli emas: Telegram'da eski xabardagi tugma
    keyin ham bosiladi, callback_data'ni qo'lda yuborish ham mumkin. Shuning
    uchun ko'rsatish (menyu/yordam) va bajarish (shu tekshiruv) — ikkovi
    alohida, lekin bitta `core.logic.permissions` jadvaliga tayanadi.

    T-9 — XABARLAR uchun bu ICHKI (inner) middleware, callback'lar uchun esa
    TASHQI (outer). Sabab aiogram'ning tartibida: tashqi middleware router
    filtrlaridan OLDIN ishlaydi, ya'ni `IsAdmin` hali `current_admin`ni
    in'ektsiya qilmagan bo'ladi — o'shanda bu tekshiruv `admin is None` deb
    JIMGINA o'tkazib yuborardi va buyruqlar umuman tekshirilmasdi. Ichki
    middleware filtrlardan KEYIN ishlaydi, demak `current_admin` joyida
    bo'ladi. Callback'larda esa router filtri yo'q, shuning uchun u yerda
    adminni middleware o'zi topadi (pastdagi shoxga qarang).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        admin: Admin | None = data.get("current_admin")

        if admin is None and isinstance(event, CallbackQuery) and event.from_user is not None:
            # Callback'larda `IsAdmin` filtri ishlamaydi (u faqat message
            # uchun) — shuning uchun adminni shu yerda topamiz va keyingi
            # handler'lar ham foydalanishi uchun `data`ga qo'yamiz.
            async with get_session() as session:
                admin = await get_admin_by_tg_id(session, event.from_user.id)
            if admin is None or not admin.is_active:
                await event.answer("Sizda ruxsat yo'q.", show_alert=True)
                return None
            data["current_admin"] = admin

        if admin is None:
            # Xabarlarda bu yerga faqat `IsAdmin` o'tkazmagan holat kelishi
            # mumkin emas (u o'tkazmasa handler ham chaqirilmaydi), lekin
            # ehtiyot uchun: adminni aniqlay olmasak, ruxsat ham bera olmaymiz.
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/"):
                command = text[1:].split()[0].split("@")[0].lower()
                if command in perms.COMMANDS and not perms.can_use_command(admin, command):
                    await event.answer(perms.denial_message(admin, "/" + command))
                    return None
            elif text in perms.MENU_BUTTONS and not perms.can_use_menu_button(admin, text):
                await event.answer(perms.denial_message(admin, text))
                return None

        elif isinstance(event, CallbackQuery) and event.data:
            if not perms.can_use_callback(admin, event.data):
                await event.answer(
                    "⛔ Bu amal sizning rolingizga ochiq emas.", show_alert=True
                )
                return None

        return await handler(event, data)


# T-9 — xabarlar: ICHKI (filtrlardan keyin, `current_admin` bor);
# callback'lar: TASHQI (router filtri yo'q, middleware o'zi topadi).
admin_router.message.middleware(RolePermission())
admin_router.callback_query.outer_middleware(RolePermission())


async def _guard(callback: CallbackQuery) -> Admin | None:
    """Inline tugma bosgan odam haqiqatan adminmi (TZ 12.2).

    Audit K-4 — endi `bool` emas, topilgan `Admin` qatorini (yoki `None`ni)
    qaytaradi, chunki ko'p handler'larga ko'rish-cheklash uchun joriy
    adminning id/roli kerak bo'ladi. Mavjud `if not await _guard(...): return`
    chaqiruvlari o'zgarishsiz to'g'ri ishlayveradi (`None` ham "yolg'on").
    """
    if callback.from_user is None:
        return None
    async with get_session() as session:
        admin = await get_admin_by_tg_id(session, callback.from_user.id)
    if admin is None:
        await callback.answer("Sizda ruxsat yo'q.", show_alert=True)
        return None
    return admin


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    """Xabarni tahrirlash — bir xil matn bo'lsa Telegram xato beradi, ushlaymiz."""
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


# MUHIM: model obyektlaridan matn/klaviatura yasash HAR DOIM sessiya ICHIDA
# bo'lishi kerak. `users.last_seen` va `cases.updated_at` ustunlarida
# `onupdate=func.now()` bor — UPDATE'dan keyin SQLAlchemy ularni "eskirgan"
# deb belgilaydi va sessiya yopilgach o'qishga urinish `DetachedInstanceError`
# beradi (`expire_on_commit=False` bunga yordam bermaydi, chunki gap
# server tomonida hisoblanadigan ustunlarda).


# --------------------------------------------------------------------------- #
# Boshlash / yordam
# --------------------------------------------------------------------------- #


@admin_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, current_admin: Admin) -> None:
    await state.clear()
    await message.answer(
        views.welcome(message.from_user.first_name if message.from_user else None)
        + f"\n\nRolingiz: {perms.role_label(current_admin.role)}",
        reply_markup=kb.main_menu(current_admin),
    )


@admin_router.message(Command("help"))
@admin_router.message(F.text == kb.BTN_HELP)
async def show_help(message: Message, current_admin: Admin) -> None:
    """Har kim FAQAT o'ziga ochiq buyruqlarni ko'radi (TZ 14, Q43).

    Guruhda ham ishlaydi — ro'yxat tugmani bosgan odamning roliga qarab
    tuziladi, ya'ni bitta guruhdagi ikki xil xodim ikki xil ro'yxat oladi.
    """
    in_group = message.chat.type in ("group", "supergroup")
    await message.answer(
        views.help_for_role(current_admin, in_group=in_group),
        reply_markup=None if in_group else kb.main_menu(current_admin),
    )


@admin_router.message(Command("myrole"))
async def show_my_role(message: Message, current_admin: Admin) -> None:
    allowed = perms.allowed_commands(current_admin)
    await message.answer(
        f"👤 <b>{current_admin.name}</b>\n\n"
        f"Rolingiz: {perms.role_label(current_admin.role)}\n"
        f"Sizga ochiq buyruqlar: <b>{len(allowed)}</b> ta\n\n"
        f"To'liq ro'yxat uchun /help yuboring."
    )


@admin_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    # Audit N-2 — boshqa barcha callback handler'lardan farqli, bu ikkovi
    # `_guard()` chaqirmasdi. Amaliy xavfi past (bu tugmalar faqat
    # adminlarga yuborilgan xabarlarda ko'rinadi), lekin izchillik uchun
    # va kelajakda kod ko'chirilganda/qayta ishlatilganda xato manbai
    # bo'lmasligi uchun qo'shildi.
    if await _guard(callback) is None:
        return
    await callback.answer()


@admin_router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if await _guard(callback) is None:  # Audit N-2
        return
    await state.clear()
    await _edit(callback, "Bekor qilindi.")
    await callback.answer()


# --------------------------------------------------------------------------- #
# Statistika (TZ 10-bo'lim)
# --------------------------------------------------------------------------- #


@admin_router.message(Command("stats"))
@admin_router.message(F.text == kb.BTN_STATS)
async def show_stats(message: Message, current_admin: Admin) -> None:
    # §8.4 — oddiy admin faqat o'zinikini ko'radi (`/vstats` va `/problems`
    # allaqachon shunday; bu eski ekran ochiq qolib ketgan edi).
    can_all = can_see_everything(current_admin)
    async with get_session() as session:
        stats = await gather_stats(
            session, viewer_admin_id=current_admin.id, can_see_all=can_all
        )
    await message.answer(views.stats_text(stats, own_only=not can_all))


# --------------------------------------------------------------------------- #
# Botlar (TZ 3.3, 9.5, 12)
# --------------------------------------------------------------------------- #


@admin_router.message(Command("bots"))
@admin_router.message(F.text == kb.BTN_BOTS)
async def show_bots(message: Message) -> None:
    async with get_session() as session:
        bots = await list_bots(session)
    await message.answer(views.bots_summary(bots), reply_markup=kb.bots_list(bots))


@admin_router.callback_query(F.data == "nav:bots")
async def cb_bots(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        bots = await list_bots(session)
        text, markup = views.bots_summary(bots), kb.bots_list(bots)
    await _edit(callback, text, markup)
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^bot:\d+$"))
async def cb_bot_card(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    bot_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        bot = await get_bot(session, bot_id)
        if bot is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return
        text, markup = views.bot_card(bot), kb.bot_card(bot)
    await _edit(callback, text, markup)
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^bot:\d+:(on|off)$"))
async def cb_bot_toggle(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, raw_id, action = callback.data.split(":")
    bot_id, activate = int(raw_id), action == "on"

    async with get_session() as session:
        bot = await set_bot_active(session, bot_id, activate)
        if bot is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return
        await log_action(
            session,
            callback.from_user.id,
            "bot_active",
            f"@{bot.username} -> {'yoqildi' if activate else 'ochirildi'}",
        )
        text, markup = views.bot_card(bot), kb.bot_card(bot)

    await _edit(callback, text, markup)
    await callback.answer("Yoqildi." if activate else "Vaqtincha o'chirildi.")


@admin_router.callback_query(F.data.regexp(r"^bot:\d+:fmt$"))
async def cb_bot_format_menu(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    bot_id = int(callback.data.split(":")[1])
    await _edit(
        callback,
        "📱 Bot bilan nomer qaysi ko'rinishda almashiladi? (TZ 9.5)\n\n"
        "Turli botlar turlicha kutishi mumkin — shu bot uchun tanlang:",
        kb.bot_format_choice(bot_id),
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^bot:\d+:fmt:\d+$"))
async def cb_bot_format_set(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, raw_id, _, raw_idx = callback.data.split(":")
    bot_id, idx = int(raw_id), int(raw_idx)
    if idx >= len(PHONE_FORMATS):
        await callback.answer("Noma'lum format.", show_alert=True)
        return
    fmt = PHONE_FORMATS[idx]

    async with get_session() as session:
        bot = await set_bot_phone_format(session, bot_id, fmt)
        if bot is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return
        await log_action(session, callback.from_user.id, "bot_format", f"@{bot.username} -> {fmt}")
        text, markup = views.bot_card(bot), kb.bot_card(bot)

    await _edit(callback, text, markup)
    await callback.answer(f"Format: {fmt}")


@admin_router.callback_query(F.data.regexp(r"^bot:\d+:free$"))
async def cb_bot_force_free(callback: CallbackQuery) -> None:
    """TZ 12 — osilib qolgan botni majburan bo'shatish (lane leak oldini olish).

    Audit J-4 — avval bu yerda YANGI, DISKONNEKT `BotPoolManager()` yaratib
    faqat DB bayrog'i tozalanardi — bu Teletonning HAQIQIY, jarayon-ichidagi
    navbatiga (`pool._queue`) hech qanday ta'sir qilmasdi: agar hamma bot
    band bo'lib case'lar navbatda kutayotgan bo'lsa, "bo'shatilgan" bot
    navbatdagi case'ni olmasdan bekorga bo'sh turaverardi. Endi
    `admin_redispatch_requested` bilan bir xil naqsh ishlatiladi.
    """
    if not await _guard(callback):
        return
    bot_id = int(callback.data.split(":")[1])

    async with get_session() as session:
        bot = await request_bot_force_release(session, bot_id)
        if bot is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return
        await log_action(session, callback.from_user.id, "bot_force_free", f"@{bot.username}")
        text, markup = views.bot_card(bot), kb.bot_card(bot)

    await _edit(callback, text, markup)
    await callback.answer("So'rov yuborildi — Teleton tez orada bo'shatadi.")


@admin_router.callback_query(F.data == "bot:add")
async def cb_bot_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    await state.set_state(AddBotFlow.waiting_username)
    await _edit(
        callback,
        "➕ <b>Yangi tekshiruv bot</b>\n\n"
        "Bot username'ini yuboring (masalan <code>NB_nazoratchibot</code> — "
        "@ belgisi shart emas).",
        kb.cancel_only(),
    )
    await callback.answer()


@admin_router.message(AddBotFlow.waiting_username)
async def on_new_bot_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip().lstrip("@")
    if not username or " " in username:
        await message.answer("Username noto'g'ri. Bitta so'z bo'lishi kerak, qayta yuboring.")
        return
    await state.update_data(username=username)
    await message.answer(
        f"@{username} uchun nomer formatini tanlang (TZ 9.5):",
        reply_markup=kb.new_bot_format_choice(),
    )


@admin_router.callback_query(F.data.regexp(r"^newbot:fmt:\d+$"), AddBotFlow.waiting_username)
async def cb_new_bot_format(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    idx = int(callback.data.split(":")[2])
    if idx >= len(PHONE_FORMATS):
        await callback.answer("Noma'lum format.", show_alert=True)
        return
    await state.update_data(phone_format=PHONE_FORMATS[idx])
    await _edit(
        callback,
        "Bu bot bilan suhbatni boshlash uchun avval <code>/start</code> "
        "yuborish kerakmi? (Q54 — ba'zi botlar talab qiladi)",
        kb.new_bot_start_choice(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^newbot:start:[01]$"), AddBotFlow.waiting_username)
async def cb_new_bot_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    needs_start = callback.data.split(":")[2] == "1"
    data = await state.get_data()
    username = data.get("username")
    phone_format = data.get("phone_format", PHONE_FORMATS[0])
    await state.clear()

    async with get_session() as session:
        bot = await add_bot(session, username, phone_format, needs_start_greeting=needs_start)
        if bot is not None:
            await log_action(
                session,
                callback.from_user.id,
                "addbot",
                f"@{username} ({phone_format}, start={needs_start})",
            )
        bots = await list_bots(session)
        summary, markup = views.bots_summary(bots), kb.bots_list(bots)

    if bot is None:
        await _edit(callback, f"@{username} allaqachon pool'da mavjud.", markup)
        await callback.answer("Mavjud.", show_alert=True)
        return

    await _edit(callback, summary, markup)
    await callback.answer(f"@{username} qo'shildi.")


# --------------------------------------------------------------------------- #
# Shablonlar — mijozga (7.2) va bot-tanish (7.1), ALOHIDA (Q47)
# --------------------------------------------------------------------------- #

_TPL_ROOT_TEXT = (
    "📝 <b>Shablonlar</b>\n\n"
    "Ikki xil to'plam bor va ular ARALASHTIRILMAYDI (TZ 7-bo'lim, Q47):\n\n"
    "💬 <b>Mijozga yuboriladigan</b> — mijoz o'qiydigan matnlar.\n"
    "🤖 <b>Bot javobini tanish</b> — tekshiruv botning javobini tushunish uchun "
    "namunalar. Bular mijozga HECH QACHON yuborilmaydi."
)


@admin_router.message(Command("templates"))
@admin_router.message(F.text == kb.BTN_TEMPLATES)
async def show_templates_root(message: Message) -> None:
    await message.answer(_TPL_ROOT_TEXT, reply_markup=kb.templates_root())


@admin_router.callback_query(F.data == "nav:templates")
async def cb_templates_root(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    await _edit(callback, _TPL_ROOT_TEXT, kb.templates_root())
    await callback.answer()


@admin_router.callback_query(F.data == "nav:tpl_customer")
async def cb_tpl_customer(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    await _edit(
        callback,
        "💬 <b>Mijozga yuboriladigan shablonlar</b> (TZ 7.2)\n\nKo'rish/tahrirlash uchun tanlang:",
        kb.template_keys(DEFAULTS.keys(), "c"),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "nav:tpl_bot")
async def cb_tpl_bot(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        missing = await missing_patterns(session)
    warn = (
        f"\n\n❗ To'ldirilmagan: {', '.join(missing)} — real bot rejimi bunda ishga tushmaydi (Q16)."
        if missing
        else "\n\n✅ Hammasi to'ldirilgan."
    )
    await _edit(
        callback,
        "🤖 <b>Bot javobini tanish shablonlari</b> (TZ 7.1)\n\n"
        "Bular tekshiruv botning O'Z javobini tanish uchun — mijozga yuborilmaydi." + warn,
        kb.template_keys(BOT_PATTERN_KEYS, "b"),
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^tpl:[cb]:[A-Z_]+$"))
async def cb_template_card(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, kind, key = callback.data.split(":")

    async with get_session() as session:
        if kind == "c":
            value = await get_template(session, key)
            title = "💬 Mijozga yuboriladigan"
        else:
            patterns = await list_bot_patterns(session)
            value = patterns.get(key)
            title = "🤖 Bot javobini tanish"

    shown = value if value else "<i>❌ kiritilmagan</i>"
    await _edit(
        callback,
        f"{title}\n\n<b>{key}</b>\n\n{shown}",
        kb.template_card(kind, key),
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^tpl:[cb]:[A-Z_]+:edit$"))
async def cb_template_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    _, kind, key, _ = callback.data.split(":")
    await state.update_data(key=key)
    await state.set_state(
        EditTemplateFlow.waiting_text if kind == "c" else EditPatternFlow.waiting_text
    )
    hint = (
        "Mijoz shu matnni o'qiydi."
        if kind == "c"
        else "Bot javobining bir bo'lagini yozing — kichik/katta harf farqi yo'q, "
        "javob ichida shu matn bo'lsa yetarli."
    )
    await _edit(callback, f"✏️ <b>{key}</b> uchun yangi matnni yuboring.\n\n{hint}", kb.cancel_only())
    await callback.answer()


@admin_router.message(EditTemplateFlow.waiting_text)
async def on_template_text(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("Matn bo'sh. Qayta yuboring.")
        return
    key = (await state.get_data())["key"]
    await state.clear()

    async with get_session() as session:
        await set_template(session, key, value)
        await log_action(session, message.from_user.id, "settemplate", f"{key} -> {value}")

    await message.answer(
        f"✅ <b>{key}</b> yangilandi:\n\n{value}", reply_markup=kb.template_card("c", key)
    )


@admin_router.message(EditPatternFlow.waiting_text)
async def on_pattern_text(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("Matn bo'sh. Qayta yuboring.")
        return
    key = (await state.get_data())["key"]
    await state.clear()

    async with get_session() as session:
        await set_bot_pattern(session, key, value)
        await log_action(session, message.from_user.id, "setbotpattern", f"{key} -> {value}")

    await message.answer(
        f"✅ <b>{key}</b> yangilandi:\n\n{value}", reply_markup=kb.template_card("b", key)
    )


# --------------------------------------------------------------------------- #
# Muammolar / navbat — sahifalangan ro'yxat (TZ 9.2)
# --------------------------------------------------------------------------- #


async def _case_page(kind: str, page: int, current_admin: Admin):
    statuses = PROBLEM_STATUSES if kind == "pr" else [CaseStatus.NUMBER_RECEIVED]
    can_all = can_see_everything(current_admin)
    async with get_session() as session:
        # Audit K-4 (TZ 11.0, Q51) — oddiy admin faqat o'ziga biriktirilgan
        # (yoki hali hech kimga biriktirilmagan) mijozlarning case'larini
        # ko'radi; Owner/Rop hammasini ko'radi.
        cases = await list_cases_by_statuses(
            session,
            statuses,
            limit=200,
            viewer_admin_id=current_admin.id,
            can_see_all=can_all,
        )
    total = len(cases)
    start = page * kb.PAGE_SIZE
    return cases[start : start + kb.PAGE_SIZE], total


@admin_router.message(Command("problems"))
@admin_router.message(F.text == kb.BTN_PROBLEMS)
async def show_problems(message: Message, current_admin: Admin) -> None:
    page_items, total = await _case_page("pr", 0, current_admin)
    await message.answer(
        views.case_list_text("pr", total), reply_markup=kb.case_list(page_items, "pr", 0, total)
    )


@admin_router.message(Command("pending"))
@admin_router.message(F.text == kb.BTN_PENDING)
async def show_pending(message: Message, current_admin: Admin) -> None:
    page_items, total = await _case_page("pn", 0, current_admin)
    await message.answer(
        views.case_list_text("pn", total), reply_markup=kb.case_list(page_items, "pn", 0, total)
    )


@admin_router.callback_query(F.data.regexp(r"^nav:(problems|pending)$"))
async def cb_case_list_root(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    kind = "pr" if callback.data.endswith("problems") else "pn"
    page_items, total = await _case_page(kind, 0, admin)
    await _edit(
        callback, views.case_list_text(kind, total), kb.case_list(page_items, kind, 0, total)
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^pg:(pr|pn):\d+$"))
async def cb_case_page(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    _, kind, raw_page = callback.data.split(":")
    page = int(raw_page)
    page_items, total = await _case_page(kind, page, admin)
    await _edit(
        callback, views.case_list_text(kind, total), kb.case_list(page_items, kind, page, total)
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^cs:\d+(:(pr|pn):\d+|:sr:\d+:\d+)?$"))
async def cb_case_card(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    parts = callback.data.split(":")
    case_id = int(parts[1])

    # Audit O-3 — case ro'yxatidan ("pr"/"pn"/"sr") kelingan bo'lsa, "⬅️
    # Orqaga" tugmasi shu manbaga (aynan o'sha sahifaga) qaytishi uchun
    # callback_data'dagi manba ma'lumoti o'qiladi. Yo'q bo'lsa (masalan
    # notifier alertidan to'g'ridan-to'g'ri kelingan bo'lsa) standart
    # "Muammolar" ro'yxatiga qaytadi.
    back = "nav:problems"
    if len(parts) == 4 and parts[2] in ("pr", "pn"):
        back = f"pg:{parts[2]}:{parts[3]}"
    elif len(parts) == 5 and parts[2] == "sr":
        back = f"pg:sr:{parts[3]}:{parts[4]}"

    can_all = can_see_everything(admin)
    async with get_session() as session:
        bundle = await get_case_bundle(
            session, case_id, viewer_admin_id=admin.id, can_see_all=can_all
        )
        if bundle is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        case, user, attempts = bundle
        text, markup = views.case_card(case, user, attempts), kb.case_card(case, user, back=back)
    await _edit(callback, text, markup)
    await callback.answer()


# --------------------------------------------------------------------------- #
# TZ 9.3 — "Noaniq natijada: [Tasdiqlash] [Rad] [Qayta uzatish]"
# --------------------------------------------------------------------------- #


@admin_router.callback_query(F.data.regexp(r"^cs:\d+:(ok|no|again)$"))
async def cb_case_resolve(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    _, raw_id, action = callback.data.split(":")
    case_id = int(raw_id)
    can_all = can_see_everything(admin)

    async with get_session() as session:
        # Audit K-4 — boshqa adminga biriktirilgan case ustida amal
        # bajarilishidan oldin ko'rish huquqi tekshiriladi.
        visible = await get_case_bundle(
            session, case_id, viewer_admin_id=admin.id, can_see_all=can_all
        )
        if visible is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        try:
            if action == "ok":
                case = await manual_confirm(session, case_id)
                label, note = "manual_confirm", "✅ Qo'lda TASDIQLANDI."
            elif action == "no":
                case = await manual_reject(session, case_id)
                label, note = "manual_reject", "❌ Qo'lda RAD ETILDI."
            else:
                case = await request_redispatch(session, case_id)
                label, note = (
                    "request_redispatch",
                    "🔄 Qayta uzatish so'raldi — Teleton bo'sh bot topib mijozdan "
                    "kuponni qaytadan so'raydi.",
                )
        except InvalidCaseStateError:
            # Audit K-3 — case holati bu amal ko'rsatilgandan keyin allaqachon
            # o'zgargan (masalan boshqa admin yoki Teleton uni yopib ulgurgan) —
            # eskirgan tugmani yana bosishga urinilgan. Hech narsa o'zgartirmay,
            # kartochkani joriy (haqiqiy) holat bilan yangilab ko'rsatamiz.
            bundle = await get_case_bundle(session, case_id)
            if bundle is None:
                await callback.answer("Murojaat topilmadi.", show_alert=True)
                return
            case, user, attempts = bundle
            text = (
                views.case_card(case, user, attempts)
                + "\n\n⚠️ Bu murojaat holati allaqachon o'zgargan — bu amalni "
                "endi bajarib bo'lmaydi."
            )
            markup = kb.case_card(case, user)
            await _edit(callback, text, markup)
            await callback.answer("Holat allaqachon o'zgargan.", show_alert=True)
            return

        if case is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        await log_action(session, callback.from_user.id, label, f"case #{case_id}")
        case, user, attempts = await get_case_bundle(session, case_id)
        text = views.case_card(case, user, attempts) + f"\n\n{note}"
        markup = kb.case_card(case, user)

    await _edit(callback, text, markup)
    await callback.answer(note.split(".")[0])


# --------------------------------------------------------------------------- #
# Shubhali holat: Xavfsiz / Bloklash (TZ 5.2, 9.3)
# --------------------------------------------------------------------------- #
#
# DIQQAT: `safe:` / `block:` callback_data'lari `core/logic/notifier.py`
# yuboradigan ogohlantirish xabarlarida ham ishlatiladi — nomlarni
# o'zgartirmaslik kerak, aks holda eski alertlardagi tugmalar ishlamay qoladi.
#
# Bu yerda faqat DB bayroqlari o'zgaradi. Haqiqiy dispatch (bot biriktirish,
# mijozga Telethon orqali xabar) Teleton jarayonidagi fon kuzatuvchisi
# tomonidan bajariladi — faqat u mijoz bilan "admin nomidan" gaplasha oladi.


@admin_router.callback_query(F.data.startswith("safe:"))
async def cb_mark_safe(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    case_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        case = await session.get(Case, case_id)
        if case is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        await set_user_safe(session, case.user_id, True)
        await log_action(session, callback.from_user.id, "mark_safe", f"case #{case_id}")

    await _edit(
        callback,
        (callback.message.text or "") + "\n\n✅ XAVFSIZ deb belgilandi — Teleton dispatch qiladi.",
    )
    await callback.answer("Xavfsiz deb belgilandi.")


@admin_router.callback_query(F.data.startswith("block:"))
async def cb_block_user(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    case_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        case = await session.get(Case, case_id)
        if case is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        await set_user_blocked(session, case.user_id, True)
        case.status = CaseStatus.REJECTED
        await session.commit()
        await log_action(session, callback.from_user.id, "block_user", f"case #{case_id}")

    await _edit(callback, (callback.message.text or "") + "\n\n🚫 BLOKLANDI.")
    await callback.answer("Foydalanuvchi bloklandi.")


# --------------------------------------------------------------------------- #
# Mijoz kartochkasi (TZ 11.1 — CRM)
# --------------------------------------------------------------------------- #


async def _load_visible_user(session, user_id: int, admin: Admin) -> User | None:
    """Audit K-4 — mijozni faqat ko'rish huquqi bo'lsa qaytaradi (boshqa
    adminga biriktirilgan bo'lsa `None` — "topilmadi" bilan bir xil javob)."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    if not can_see_everything(admin):
        if user.assigned_admin_id is not None and user.assigned_admin_id != admin.id:
            return None
    return user


@admin_router.callback_query(F.data.regexp(r"^usr:\d+$"))
async def cb_user_card(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    user_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        user = await _load_visible_user(session, user_id, admin)
        if user is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
        cases = await cases_for_user(session, user_id)
        text = views.user_card(user, cases)
        markup = kb.user_card(user, can_assign=can_see_everything(admin), viewer_admin_id=admin.id)
    await _edit(callback, text, markup)
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:(block|unblock|safe)$"))
async def cb_user_flag(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    _, raw_id, action = callback.data.split(":")
    user_id = int(raw_id)

    async with get_session() as session:
        if await _load_visible_user(session, user_id, admin) is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return

        if action == "block":
            user = await set_user_blocked(session, user_id, True)
            label, note = "block_user", "Bloklandi."
        elif action == "unblock":
            user = await set_user_blocked(session, user_id, False)
            label, note = "unblock_user", "Blokdan chiqarildi."
        else:
            user = await set_user_safe(session, user_id, True)
            label, note = "mark_safe", "Xavfsiz deb belgilandi."

        await log_action(session, callback.from_user.id, label, f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text = views.user_card(user, cases)
        markup = kb.user_card(user, can_assign=can_see_everything(admin), viewer_admin_id=admin.id)

    await _edit(callback, text, markup)
    await callback.answer(note)


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:note$"))
async def cb_user_note(callback: CallbackQuery, state: FSMContext) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    user_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        if await _load_visible_user(session, user_id, admin) is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
    await state.update_data(user_id=user_id)
    await state.set_state(UserNoteFlow.waiting_note)
    await _edit(
        callback,
        "📝 Mijoz haqida izohni yuboring (CRM uchun, TZ 11.1).\n\n"
        "<i>Eski izoh bo'lsa almashtiriladi.</i>",
        kb.cancel_only(),
    )
    await callback.answer()


@admin_router.message(UserNoteFlow.waiting_note)
async def on_user_note(message: Message, state: FSMContext, current_admin: Admin) -> None:
    note = (message.text or "").strip()
    if not note:
        await message.answer("Izoh bo'sh. Qayta yuboring.")
        return
    user_id = (await state.get_data())["user_id"]
    await state.clear()

    async with get_session() as session:
        if await _load_visible_user(session, user_id, current_admin) is None:
            await message.answer("Mijoz topilmadi.")
            return
        user = await set_user_note(session, user_id, note)
        await log_action(session, message.from_user.id, "user_note", f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text = views.user_card(user, cases)
        markup = kb.user_card(
            user, can_assign=can_see_everything(current_admin), viewer_admin_id=current_admin.id
        )

    await message.answer(text, reply_markup=markup)


# --------------------------------------------------------------------------- #
# Mijozni adminga biriktirish (TZ 11.0/11.1, Q51) — K-4
# --------------------------------------------------------------------------- #


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:claim$"))
async def cb_user_claim(callback: CallbackQuery) -> None:
    """Har qanday admin hali hech kimga biriktirilmagan mijozni "o'ziga
    olishi" mumkin — shundan keyin faqat Owner/Rop + shu admin ko'radi."""
    admin = await _guard(callback)
    if admin is None:
        return
    user_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        user = await _load_visible_user(session, user_id, admin)
        if user is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
        if user.assigned_admin_id is not None and user.assigned_admin_id != admin.id:
            await callback.answer("Bu mijoz allaqachon boshqa adminga biriktirilgan.", show_alert=True)
            return
        user = await assign_customer(session, user_id, admin.id)
        await log_action(session, callback.from_user.id, "claim_customer", f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text = views.user_card(user, cases)
        markup = kb.user_card(user, can_assign=can_see_everything(admin), viewer_admin_id=admin.id)
    await _edit(callback, text, markup)
    await callback.answer("Sizga biriktirildi.")


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:unassign$"))
async def cb_user_unassign(callback: CallbackQuery) -> None:
    """Owner/Rop — mijozni "hech kimga biriktirilmagan" holatga qaytaradi."""
    admin = await _guard(callback)
    if admin is None:
        return
    if not can_see_everything(admin):
        await callback.answer("Faqat Owner/Rop bu amalni bajara oladi.", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        user = await assign_customer(session, user_id, None)
        if user is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
        await log_action(session, callback.from_user.id, "unassign_customer", f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text = views.user_card(user, cases)
        markup = kb.user_card(user, can_assign=True, viewer_admin_id=admin.id)
    await _edit(callback, text, markup)
    await callback.answer("Biriktirish bekor qilindi.")


# --------------------------------------------------------------------------- #
# Nomer bo'yicha qidiruv (TZ 9.2 — `drop find`)
# --------------------------------------------------------------------------- #


@admin_router.message(F.text == kb.BTN_SEARCH)
async def start_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchFlow.waiting_phone)
    await message.answer(
        "🔍 Qidirilayotgan nomerni yuboring.\n\n"
        "<i>Masalan:</i> <code>998901234567</code> yoki <code>+998 90 123 45 67</code>",
        reply_markup=kb.cancel_only(),
    )


@admin_router.message(SearchFlow.waiting_phone)
async def on_search_phone(message: Message, state: FSMContext, current_admin: Admin) -> None:
    phone = extract_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Nomer tanilmadi. O'zbekiston formatida yuboring (masalan 998901234567)."
        )
        return
    await state.clear()
    await _send_search_results(message, phone, current_admin)


@admin_router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
    async with get_session() as session:
        entries = await list_recent(session, limit=20)
    await message.answer(views.audit_text(entries))


@admin_router.message(F.text.func(lambda t: t and t.lower().startswith("drop find")))
async def cmd_drop_find(message: Message, current_admin: Admin) -> None:
    raw = message.text[len("drop find") :].strip()
    phone = extract_phone(raw) if raw else None
    if phone is None:
        await message.answer(
            "Format: <code>drop find &lt;nomer&gt;</code>\n"
            "Yoki menyudagi 🔍 <b>Nomer qidirish</b> tugmasidan foydalaning."
        )
        return
    await _send_search_results(message, phone, current_admin)


@admin_router.message(
    ~F.text.startswith("/"),
    F.text.func(lambda t: t and extract_phone(t) is not None),
)
async def on_bare_phone(message: Message, current_admin: Admin) -> None:
    """Admin shunchaki nomer yuborsa — darhol qidiruv (qulaylik uchun).

    Buyruqlar ataylab chetlab o'tiladi: `/settemplate CONFIRMED ... 998901234567 ...`
    kabi ichida nomer bo'lgan buyruq bu handler'ga tushib ketmasligi kerak
    (u ro'yxatda buyruq handler'laridan oldin turadi).
    """
    await _send_search_results(message, extract_phone(message.text), current_admin)


async def _search_case_page(phone: str, page: int, current_admin: Admin):
    can_all = can_see_everything(current_admin)
    async with get_session() as session:
        # Audit K-4 (TZ 11.0, Q51) — qidiruv ham ko'rish-cheklashiga bo'ysunadi.
        cases = await search_cases(
            session, phone=phone, viewer_admin_id=current_admin.id, can_see_all=can_all
        )
    total = len(cases)
    start = page * kb.PAGE_SIZE
    return cases[start : start + kb.PAGE_SIZE], total


async def _send_search_results(message: Message, phone: str, current_admin: Admin) -> None:
    page_items, total = await _search_case_page(phone, 0, current_admin)

    if total == 0:
        await message.answer(f"<code>{phone}</code> bo'yicha murojaat topilmadi.")
        return

    header = f"🔍 <code>{phone}</code> — {total} ta murojaat:"
    # Audit J-6 — avval `total` argumenti qattiq kodlangan 0 edi, shuning
    # uchun 8 tadan ortiq natija bo'lsa sahifalash tugmalari HECH QACHON
    # chiqmasdi — qolgan natijalarga UI orqali umuman yetib bo'lmasdi.
    # Endi haqiqiy `total` va o'ziga xos "sr" kind + nomer (`extra`) orqali
    # to'g'ri sahifalanadi.
    await message.answer(
        header, reply_markup=kb.case_list(page_items, "sr", 0, total, extra=phone)
    )


@admin_router.callback_query(F.data.regexp(r"^pg:sr:\d+:\d+$"))
async def cb_search_page(callback: CallbackQuery) -> None:
    admin = await _guard(callback)
    if admin is None:
        return
    _, _, phone, raw_page = callback.data.split(":")
    page = int(raw_page)
    page_items, total = await _search_case_page(phone, page, admin)
    header = f"🔍 <code>{phone}</code> — {total} ta murojaat:"
    await _edit(callback, header, kb.case_list(page_items, "sr", page, total, extra=phone))
    await callback.answer()


# --------------------------------------------------------------------------- #
# Sozlamalar (TZ 9.1, 11.5)
# --------------------------------------------------------------------------- #


@admin_router.message(F.text == kb.BTN_SETTINGS)
async def show_settings(message: Message) -> None:
    async with get_session() as session:
        verbose = await is_verbose(session)
    await message.answer("⚙️ <b>Sozlamalar</b>", reply_markup=kb.settings_menu(verbose))


@admin_router.callback_query(F.data == "nav:settings")
async def cb_settings(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        verbose = await is_verbose(session)
    await _edit(callback, "⚙️ <b>Sozlamalar</b>", kb.settings_menu(verbose))
    await callback.answer()


@admin_router.message(Command("notify"))
async def cmd_notify(message: Message) -> None:
    async with get_session() as session:
        verbose = await is_verbose(session)
    await message.answer(_notify_text(verbose), reply_markup=kb.notify_choice(verbose))


def _notify_text(verbose: bool) -> str:
    return (
        "🔔 <b>Bildirishnoma rejimi</b> (TZ 9.1)\n\n"
        f"Joriy: <b>{'batafsil — hamma hodisa' if verbose else 'oddiy — faqat muhim'}</b>\n\n"
        "<i>Muhim hodisalar (tasdiq, rad, timeout, shubha, navbat to'lishi) "
        "har qanday rejimda yuboriladi. Batafsil rejim qo'shimcha ravishda "
        "muddati o'tgan kupon kabi mayda hodisalarni ham yuboradi.</i>"
    )


@admin_router.callback_query(F.data == "nav:notify")
async def cb_notify_menu(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        verbose = await is_verbose(session)
    await _edit(callback, _notify_text(verbose), kb.notify_choice(verbose))
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^notify:(on|off)$"))
async def cb_notify_toggle(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    verbose = callback.data == "notify:on"
    async with get_session() as session:
        await set_verbose(session, verbose)
        await log_action(
            session, callback.from_user.id, "notify_toggle", "batafsil" if verbose else "oddiy"
        )
    await _edit(callback, _notify_text(verbose), kb.notify_choice(verbose))
    await callback.answer("Saqlandi.")


@admin_router.callback_query(F.data == "nav:audit")
async def cb_audit(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        entries = await list_recent(session, limit=20)
    await _edit(callback, views.audit_text(entries), kb.back_to("nav:settings", "⬅️ Sozlamalar"))
    await callback.answer()


@admin_router.callback_query(F.data == "nav:health")
async def cb_health(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        bots = await list_bots(session)
        missing = await missing_patterns(session)
        shadow = await is_shadow_mode(session)
    await _edit(
        callback,
        views.health_text(bots, missing, settings.use_real_verification_bots, shadow),
        kb.back_to("nav:settings", "⬅️ Sozlamalar"),
    )
    await callback.answer()


# --------------------------------------------------------------------------- #
# Operator kodlari va mijoz-timeout (TZ 2.2, 4.1) — audit J-9
# --------------------------------------------------------------------------- #


def _opcodes_text(codes: list[str]) -> str:
    return (
        "📱 <b>Operator kodlari</b> (TZ 4.1)\n\n"
        "Nomer aniqlashda haqiqiy O'zbekiston operator prefiksi sifatida "
        "qabul qilinadigan kodlar:\n\n"
        f"<code>{', '.join(codes)}</code>"
    )


@admin_router.callback_query(F.data == "nav:opcodes")
async def cb_opcodes_menu(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        codes = await get_operator_codes(session)
    await _edit(callback, _opcodes_text(codes), kb.opcodes_menu())
    await callback.answer()


@admin_router.callback_query(F.data == "opcodes:edit")
async def cb_opcodes_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    await state.set_state(EditOperatorCodesFlow.waiting_text)
    await _edit(
        callback,
        "✏️ Yangi operator kodlari ro'yxatini vergul bilan ajratib yuboring.\n\n"
        "<i>Masalan:</i> <code>90, 91, 93, 94, 95, 97, 98, 99, 33, 88, 20</code>",
        kb.cancel_only(),
    )
    await callback.answer()


@admin_router.message(EditOperatorCodesFlow.waiting_text)
async def on_opcodes_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes or not all(c.isdigit() for c in codes):
        await message.answer(
            "Noto'g'ri format. Faqat raqamlarni vergul bilan ajratib yuboring "
            "(masalan: <code>90, 91, 93</code>)."
        )
        return
    await state.clear()

    async with get_session() as session:
        await set_operator_codes(session, codes)
        await log_action(session, message.from_user.id, "set_operator_codes", ", ".join(codes))

    await message.answer(f"✅ Yangilandi:\n\n{_opcodes_text(codes)}", reply_markup=kb.opcodes_menu())


def _timeout_text(seconds: float) -> str:
    minutes = seconds / 60
    return (
        "⏱ <b>Kupon kutish vaqti</b> (TZ 2.2)\n\n"
        f"Mijoz nomer yuborgach, kupon uchun <b>{seconds:.0f} soniya</b> "
        f"(~{minutes:.1f} daqiqa) kutiladi. Shu vaqt ichida kupon kelmasa, "
        "seans to'xtatiladi va bot bo'shatiladi."
    )


@admin_router.callback_query(F.data == "nav:timeout")
async def cb_timeout_menu(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    async with get_session() as session:
        seconds = await get_customer_timeout_seconds(session)
    await _edit(callback, _timeout_text(seconds), kb.timeout_menu())
    await callback.answer()


@admin_router.callback_query(F.data == "timeout:edit")
async def cb_timeout_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    await state.set_state(EditTimeoutFlow.waiting_text)
    await _edit(
        callback,
        "✏️ Yangi kutish vaqtini SONIYADA yuboring (masalan <code>300</code> — 5 daqiqa).",
        kb.cancel_only(),
    )
    await callback.answer()


@admin_router.message(EditTimeoutFlow.waiting_text)
async def on_timeout_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        await message.answer("Noto'g'ri qiymat. Faqat son yuboring (masalan 300).")
        return
    await state.clear()

    async with get_session() as session:
        try:
            await set_customer_timeout_seconds(session, seconds)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await log_action(session, message.from_user.id, "set_customer_timeout", str(seconds))

    await message.answer(f"✅ Yangilandi:\n\n{_timeout_text(seconds)}", reply_markup=kb.timeout_menu())


# --------------------------------------------------------------------------- #
# Eski buyruqlar bilan moslik (TZ 9.2) — tugmalar asosiy yo'l bo'lsa ham
# buyruqlar ishlashda davom etadi.
# --------------------------------------------------------------------------- #


@admin_router.message(Command("addbot"))
async def cmd_addbot(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer(
            "Format: <code>/addbot &lt;username&gt; [format] [start]</code>\n\n"
            "Yoki 🤖 <b>Botlar</b> → ➕ tugmasidan foydalaning (osonroq)."
        )
        return

    parts = command.args.split()
    needs_start = False
    if parts and parts[-1].lower() == "start":
        needs_start = True
        parts = parts[:-1]
    if not parts:
        await message.answer("Username kiritilmadi.")
        return

    username = parts[0].lstrip("@")
    phone_format = parts[1] if len(parts) > 1 else PHONE_FORMATS[0]

    if phone_format not in PHONE_FORMATS:
        await message.answer(
            f"Noto'g'ri format: <code>{phone_format}</code>\n"
            f"Ruxsat etilganlar: {', '.join(PHONE_FORMATS)}"
        )
        return

    async with get_session() as session:
        bot = await add_bot(session, username, phone_format, needs_start_greeting=needs_start)
        if bot is not None:
            await log_action(
                session,
                message.from_user.id,
                "addbot",
                f"@{username} ({phone_format}, start={needs_start})",
            )
    if bot is None:
        await message.answer(f"@{username} allaqachon pool'da mavjud.")
        return
    await message.answer(views.bot_card(bot), reply_markup=kb.bot_card(bot))


@admin_router.message(Command("settemplate"))
async def cmd_settemplate(message: Message, command: CommandObject) -> None:
    await _set_via_command(message, command, kind="c")


@admin_router.message(Command("setbotpattern"))
async def cmd_setbotpattern(message: Message, command: CommandObject) -> None:
    await _set_via_command(message, command, kind="b")


async def _set_via_command(message: Message, command: CommandObject, kind: str) -> None:
    valid = DEFAULTS.keys() if kind == "c" else BOT_PATTERN_KEYS
    cmd = "settemplate" if kind == "c" else "setbotpattern"

    if not command.args or len(command.args.split(maxsplit=1)) < 2:
        keys = ", ".join(valid)
        await message.answer(
            f"Format: <code>/{cmd} &lt;KEY&gt; &lt;matn&gt;</code>\nKalitlar: {keys}\n\n"
            "Yoki 📝 <b>Shablonlar</b> tugmasidan foydalaning (osonroq)."
        )
        return

    key, value = command.args.split(maxsplit=1)
    key = key.upper()
    if key not in valid:
        await message.answer(f"Noma'lum kalit: {key}\nKalitlar: {', '.join(valid)}")
        return

    async with get_session() as session:
        if kind == "c":
            await set_template(session, key, value)
            await log_action(session, message.from_user.id, "settemplate", f"{key} -> {value}")
        else:
            await set_bot_pattern(session, key, value)
            await log_action(session, message.from_user.id, "setbotpattern", f"{key} -> {value}")

    await message.answer(f"✅ <b>{key}</b> yangilandi:\n\n{value}")


async def _admins_overview() -> tuple[str, InlineKeyboardMarkup]:
    """Adminlar ro'yxati: kim, qaysi rolda, faolmi, bugun nima qildi.

    Har qator tugma — bosilsa hodimning batafsil statistika kartochkasi
    ochiladi (`vst:d:c:<id>` — statistika bo'limi bilan bitta mexanizm).
    """
    since_today = tashkent_day_start_utc(datetime.datetime.utcnow())
    async with get_session() as session:
        admins = await list_admins(session)
        report = await gather_v2_stats(session, since_today)

    by_id = {r.admin_id: r for r in report.rows}

    lines = ["👥 <b>Adminlar</b> — kim kim ekani va bugungi holati\n"]
    buttons = []
    for a in sorted(admins, key=lambda x: (not x.is_active, x.id)):
        r = by_id.get(a.id)
        status = "🟢" if a.is_active else "🔴 nofaol"
        today = (
            f"bugun: {r.cases} nomer · ✅{r.passed}"
            if r is not None and (r.cases or r.checked or r.batches)
            else "bugun: 💤 faoliyat yo'q"
        )
        lines.append(
            f"{status} <b>{display_name(a)}</b>\n"
            f"    {perms.role_label(a.role)}\n"
            f"    Telegram ID: <code>{a.tg_user_id}</code> · ichki #{a.id}\n"
            f"    {today}"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"📊 {display_name(a)} statistikasi", callback_data=f"vst:d:c:{a.id}"
            )
        ])

    lines.append(
        "\n<i>Rol berish: <code>/setrole &lt;telegram_id&gt; &lt;ROL&gt;</code> · "
        "O'chirish/yoqish: <code>/setactive &lt;telegram_id&gt; on|off</code></i>"
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@admin_router.message(Command("admins"))
async def cmd_admins(message: Message) -> None:
    """Audit K-4/J-8 — adminlar ro'yxati (TZ 14): rol izohi bilan, har biriga
    statistika kartochkasiga o'tish tugmasi."""
    text, markup = await _admins_overview()
    await message.answer(text, reply_markup=markup)


@admin_router.message(Command("setrole"))
async def cmd_setrole(message: Message, command: CommandObject, current_admin: Admin) -> None:
    """Audit K-4/J-8 — faqat OWNER boshqa adminning rolini o'zgartira oladi
    (TZ 14-bo'lim: Owner — hammasi).

    T-9 — rol tekshiruvi bu yerda EMAS, `RolePermission` middleware'da
    (`permissions.COMMANDS["setrole"]`). Ikkinchi nusxa saqlansa, ertami-kech
    jadval bilan chetlashadi."""
    if not command.args or len(command.args.split()) != 2:
        roles = ", ".join(r.value for r in AdminRole)
        await message.answer(
            f"Format: <code>/setrole &lt;telegram_id&gt; &lt;ROL&gt;</code>\nRollar: {roles}"
        )
        return
    raw_tg_id, raw_role = command.args.split()
    try:
        role = AdminRole(raw_role.upper())
    except ValueError:
        await message.answer(f"Noma'lum rol: {raw_role}")
        return
    if not raw_tg_id.lstrip("-").isdigit():
        # Avval bu yerda `int(raw_tg_id)` to'g'ridan-to'g'ri chaqirilardi va
        # raqam bo'lmasa handler xato bilan yiqilardi (foydalanuvchiga hech
        # qanday javob qaytmasdi).
        await message.answer(
            f"Telegram ID raqam bo'lishi kerak: <code>{raw_tg_id}</code>\n"
            f"ID'larni /admins ro'yxatidan oling."
        )
        return

    async with get_session() as session:
        target = await get_admin_by_tg_id(session, int(raw_tg_id))
        if target is None:
            await message.answer("Bunday telegram_id bilan admin topilmadi (avval /admins bilan tekshiring).")
            return
        # T-11 — yagona Owner pasaytirilsa, `ensure_owner_exists` keyingi
        # ishga tushishda uni jimgina qaytarib ko'taradi. Buni OLDINDAN
        # aytmasak, admin o'zini yangi rolda deb o'ylab yuradi (jonli sinovda
        # aynan shunday bo'ldi).
        oxirgi_owner = role != AdminRole.OWNER and await is_last_active_owner(
            session, target.id
        )
        updated = await set_admin_role(session, target.id, role)
        await log_action(
            session, message.from_user.id, "set_admin_role", f"admin #{updated.id} -> {role.value}"
        )

    text = f"✅ <code>{raw_tg_id}</code> endi <b>{role.value}</b>."
    if oxirgi_owner:
        kim = "Siz" if target.tg_user_id == message.from_user.id else display_name(target)
        text += (
            f"\n\n⚠️ <b>{kim} tizimdagi YAGONA faol Owner edi.</b>\n"
            f"Keyingi ishga tushishda tizim bu rolni avtomatik qaytaradi — "
            f"aks holda hech kim rol bera olmay qoladi.\n"
            f"To'g'ri tartib: avval boshqa odamni Owner qiling, keyin bu "
            f"rolni pasaytiring."
        )
    await message.answer(text)


@admin_router.message(Command("botpatterns"))
async def cmd_botpatterns(message: Message) -> None:
    async with get_session() as session:
        patterns = await list_bot_patterns(session)
    lines = [f"<b>{k}</b>\n{patterns.get(k) or '❌ kiritilmagan'}" for k in BOT_PATTERN_KEYS]
    await message.answer(
        "🤖 <b>Bot javobini tanish shablonlari</b> (mijozga yuborilmaydi)\n\n"
        + "\n\n".join(lines),
        reply_markup=kb.template_keys(BOT_PATTERN_KEYS, "b"),
    )


# --------------------------------------------------------------------------- #
# TZ v2 5.2 — nazorat guruhini belgilash (rasm partiyalari shu yerga tushadi).
# --------------------------------------------------------------------------- #


@admin_router.message(Command("setgroup"))
async def cmd_setgroup(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """Nazorat guruhini belgilaydi — TZ v2 5.2.

    Ikki usul:
    - GURUH ICHIDA `/setgroup` yozilsa — o'sha guruh belgilanadi (eng oson:
      botni guruhga qo'shib bitta buyruq).
    - Lichkada `/setgroup <chat_id>` — id qo'lda kiritiladi.

    T-9 — kimga ochiqligi `permissions.COMMANDS["setgroup"]` da (Owner +
    Dasturchi, TZ 14 "Dasturchi — texnik sozlash"). Avval bu yerda "faqat
    Owner/Rop" deb yozilgan edi: Dasturchi buyruqni /help da ko'rar,
    middleware o'tkazar, handler esa rad etardi.
    """
    if message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id
    elif command.args:
        try:
            chat_id = int(command.args.strip())
        except ValueError:
            await message.answer(
                "Format: <code>/setgroup &lt;chat_id&gt;</code> — yoki buyruqni "
                "to'g'ridan-to'g'ri nazorat guruhining ichida yozing."
            )
            return
    else:
        async with get_session() as session:
            current = await get_group_chat_id(session)
        current_text = (
            f"Joriy guruh: <code>{current}</code>" if current else "Guruh hali sozlanmagan."
        )
        await message.answer(
            f"{current_text}\n\nBelgilash uchun botni nazorat guruhiga qo'shib, "
            f"guruh ichida <code>/setgroup</code> yozing (yoki bu yerda "
            f"<code>/setgroup &lt;chat_id&gt;</code>)."
        )
        return

    async with get_session() as session:
        await set_group_chat_id(session, chat_id)
        await log_action(
            session, message.from_user.id, "set_group_chat", str(chat_id)
        )
    await message.answer(
        f"✅ Nazorat guruhi belgilandi: <code>{chat_id}</code>\n"
        f"Endi rasm partiyalari shu guruhga tushadi.\n\n"
        f"⚠️ Muhim: ADMIN akkauntlari (Telethon sessiyalari) ham shu guruhga "
        f"a'zo bo'lishi kerak — forward ular nomidan ketadi."
    )


# --------------------------------------------------------------------------- #
# TZ v2 8-bo'lim (B-5) — statistika bo'limi
#
# Tuzilishi: davr (Bugun/Kecha/Hafta/Oy/Hammasi) × ko'rinish (Umumiy /
# Hodimlar / Reyting / hodim kartochkasi). Callback formati:
#   vst:<davr>:<ko'rinish>[:<admin_id>]
# Eski `vst:d` ko'rinishidagi callback'lar ham ishlaydi (eski xabarlardagi
# tugmalar o'lik bo'lib qolmasligi uchun).
# --------------------------------------------------------------------------- #

_VSTATS_PERIODS = {
    "d": ("Bugun", 0),
    "y": ("Kecha", 1),
    "w": ("Hafta (7 kun)", 6),
    "m": ("Oy (30 kun)", 29),
    "a": ("Hammasi", 3650),
}


def _vstats_bounds(period: str) -> tuple[str, datetime.datetime, datetime.datetime | None]:
    """(sarlavha, davr boshi, davr oxiri-yoki-None)."""
    title, days_back = _VSTATS_PERIODS.get(period, _VSTATS_PERIODS["d"])
    now = datetime.datetime.utcnow()
    since = tashkent_day_start_utc(now, days_back=days_back)
    # "Kecha" — yopiq oraliq: kecha 00:00 dan bugun 00:00 gacha.
    until = tashkent_day_start_utc(now, days_back=0) if period == "y" else None
    return title, since, until


def _vstats_unrestricted(admin: Admin) -> bool:
    # TZ v2 8.4 — oddiy admin FAQAT o'zinikini ko'radi; OWNER/ROP va
    # can_view_all_stats belgilanganlar hammani ko'radi.
    #
    # T-9 izohi: bu ATAYLAB `permissions.py` ga ko'chirilmagan. U yerdagi
    # jadval "kim bu buyruqni ISHLATA oladi" degan savolga javob beradi;
    # bu yerdagi qoida esa "buyruq ichida QANCHA ma'lumot ko'rinadi" —
    # boshqa savol. `/vstats` hamma rolga ochiq, faqat qamrovi har xil.
    return admin.role in (AdminRole.OWNER, AdminRole.ROP) or admin.can_view_all_stats


def _vstats_keyboard(period: str, view: str, unrestricted: bool) -> InlineKeyboardMarkup:
    def pbtn(code: str, label: str) -> InlineKeyboardButton:
        mark = "· " if code == period else ""
        return InlineKeyboardButton(text=mark + label, callback_data=f"vst:{code}:{view}")

    rows = [
        [pbtn("d", "Bugun"), pbtn("y", "Kecha"), pbtn("w", "Hafta"),
         pbtn("m", "Oy"), pbtn("a", "Hammasi")],
    ]
    if unrestricted:
        def vbtn(code: str, label: str) -> InlineKeyboardButton:
            mark = "· " if code == view else ""
            return InlineKeyboardButton(text=mark + label, callback_data=f"vst:{period}:{code}")

        rows.append([vbtn("t", "📈 Umumiy"), vbtn("h", "👥 Hodimlar"), vbtn("r", "🏆 Reyting")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _vstats_admin_list_keyboard(period: str, report) -> InlineKeyboardMarkup:
    """Hodimlar ko'rinishi: har hodim — alohida tugma (kartochkaga kirish)."""
    rows = []
    for r in report.rows:
        if r.admin_id is None:
            continue
        flag = "💤 " if (r.cases == 0 and r.checked == 0 and r.batches == 0) else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{flag}{r.admin_name} · {r.cases} nomer · ✅{r.passed}",
                callback_data=f"vst:{period}:c:{r.admin_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Umumiy", callback_data=f"vst:{period}:t")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_vstats(
    current_admin: Admin, period: str, view: str, target_admin_id: int | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    title, since, until = _vstats_bounds(period)
    unrestricted = _vstats_unrestricted(current_admin)

    # Cheklangan admin faqat o'zini ko'radi — qaysi ko'rinish so'ralmasin.
    if not unrestricted:
        async with get_session() as session:
            cmp = await gather_with_comparison(session, since, admin_id=current_admin.id)
        own = next(
            (r for r in cmp.current.rows if r.admin_id == current_admin.id), None
        ) or AdminStatRow(admin_id=current_admin.id, admin_name=display_name(current_admin))
        prev = next(
            (r for r in cmp.previous.rows if r.admin_id == current_admin.id), None
        )
        text = render_admin_detail(own, prev, f"{title} (faqat sizniki)")
        return text, _vstats_keyboard(period, "t", unrestricted=False)

    async with get_session() as session:
        if view == "c" and target_admin_id is not None:
            cmp = await gather_with_comparison(session, since, admin_id=target_admin_id)
            row = next(
                (r for r in cmp.current.rows if r.admin_id == target_admin_id), None
            )
            if row is None:
                target = await session.get(Admin, target_admin_id)
                row = AdminStatRow(
                    admin_id=target_admin_id,
                    admin_name=display_name(target) if target else f"#{target_admin_id}",
                )
            prev = next(
                (r for r in cmp.previous.rows if r.admin_id == target_admin_id), None
            )
            text = render_admin_detail(row, prev, title)
            kb_markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬅️ Hodimlar", callback_data=f"vst:{period}:h")
            ]])
            return text, kb_markup

        if view == "h":
            report = await gather_v2_stats(session, since, until_utc=until)
            text = render_stats(report, f"Hodimlar kesimi — {title}")
            return text, _vstats_admin_list_keyboard(period, report)

        if view == "r":
            report = await gather_v2_stats(session, since, until_utc=until)
            text = render_leaderboard(report, f"Reyting — {title}")
            return text, _vstats_keyboard(period, view, unrestricted=True)

        # standart: umumiy + oldingi davr bilan solishtirish
        if until is None:
            cmp = await gather_with_comparison(session, since)
            text = render_comparison(cmp, f"Statistika — {title}")
        else:
            # "Kecha" kabi yopiq oraliqda solishtirish o'rniga oddiy ko'rinish.
            report = await gather_v2_stats(session, since, until_utc=until)
            text = render_stats(report, f"Statistika — {title}")
        return text, _vstats_keyboard(period, "t", unrestricted=True)


@admin_router.message(Command("setactive"))
async def cmd_setactive(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """TZ v2 4.2b — adminni nofaol/faol qilish (superadmin).

    Nofaol qilinganda: uning barcha ochiq case'lari MUZLATILADI (taymerlar,
    eslatmalar, avtomatik tekshiruvlar to'xtaydi — poller/drip is_active'ga
    qaraydi), Telethon klienti keyingi restart'da ishga tushirilmaydi, va
    superadminga ochiq case'lar ro'yxati ko'rsatiladi.

    T-9 — ruxsat `permissions.COMMANDS["setactive"]` da (faqat Owner).
    """
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
        await message.answer(
            "Format: <code>/setactive &lt;telegram_id&gt; on|off</code>\n"
            "(id'larni /admins ro'yxatidan oling)"
        )
        return
    make_active = parts[1].lower() == "on"

    async with get_session() as session:
        target = await get_admin_by_tg_id(session, int(parts[0]))
        if target is None:
            await message.answer("Bunday telegram_id bilan admin topilmadi.")
            return
        target.is_active = make_active
        await log_action(
            session,
            message.from_user.id,
            "set_admin_active",
            f"admin #{target.id} -> {'on' if make_active else 'off'}",
        )
        await session.commit()

        if make_active:
            await message.answer(
                f"🟢 <b>{target.name}</b> faollashtirildi. Muzlatilgan "
                f"case'lari davom etadi. Telethon sessiyasi keyingi restart'da "
                f"ulanadi."
            )
            return

        # Nofaol — ochiq case'lar ro'yxati (§4.2b: qaror superadminda).
        from core.enums import V2_OPEN_STATUSES

        result = await session.execute(
            select(Case, User)
            .join(User, Case.user_id == User.id)
            .where(
                Case.assigned_admin_id == target.id,
                Case.status.in_(list(V2_OPEN_STATUSES)),
            )
            .order_by(Case.id.desc())
        )
        open_cases = result.all()

    lines = [
        f"🔴 <b>{target.name}</b> nofaol qilindi — case'lari muzlatildi "
        f"(taymerlar, eslatmalar, tekshiruvlar to'xtadi)."
    ]
    if open_cases:
        lines.append(f"\nOchiq case'lari ({len(open_cases)} ta):")
        for case, user in open_cases[:20]:
            customer = f"@{user.tg_username}" if user.tg_username else (
                user.display_name or f"id:{user.tg_user_id}"
            )
            lines.append(
                f"· {case.short_code or case.id} — {case.phone} — {customer} "
                f"({case.status.value})"
            )
        if len(open_cases) > 20:
            lines.append(f"... va yana {len(open_cases) - 20} ta.")
        lines.append(
            "\nBu mijozlar hozir kuzatilmayapti — kimga bog'lanishni o'zingiz "
            "hal qiling."
        )
    else:
        lines.append("Ochiq case'lari yo'q.")
    await message.answer("\n".join(lines))


@admin_router.message(Command("uyqu"))
async def cmd_uyqu(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """Bot ishlab turgan KOMPYUTERNING uyqu rejimini boshqarish (superadmin).

    Tizim uy kompyuterida sinovda ishlayotganda kerak: kompyuter uxlab qolsa
    barcha jarayonlar to'xtaydi. `/uyqu off` — hech qachon uxlamaydi;
    `/uyqu on [daqiqa]` — uyqu qaytariladi (standart 30 daqiqa).

    Faqat Windows'da ishlaydi (powercfg); Linux VDS'da uyqu rejimi yo'q —
    buyruq buni o'zi aytadi.

    T-9 — ruxsat `permissions.COMMANDS["uyqu"]` da (Owner + Dasturchi:
    bu texnik sozlash, TZ 14).
    """
    import platform

    if platform.system() != "Windows":
        await message.answer(
            "Bu server Windows emas — bu yerda uyqu rejimi yo'q, "
            "buyruq shart emas."
        )
        return

    arg = (command.args or "").strip().lower()
    parts = arg.split()
    if not parts or parts[0] not in ("off", "on"):
        await message.answer(
            "Format:\n"
            "<code>/uyqu off</code> — kompyuter hech qachon uxlamaydi "
            "(sinov paytida shart)\n"
            "<code>/uyqu on</code> — uyqu qaytariladi (30 daqiqa)\n"
            "<code>/uyqu on 60</code> — uyqu qaytariladi (60 daqiqa)"
        )
        return

    if parts[0] == "off":
        minutes = 0
    else:
        minutes = 30
        if len(parts) > 1 and parts[1].isdigit():
            minutes = max(1, int(parts[1]))

    async def _powercfg(*args: str) -> int:
        proc = await asyncio.create_subprocess_exec(
            "powercfg", *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode or 0

    # AC (tokda) ham, DC (batareyada) ham — noutbuk tokdan uzilib qolsa ham
    # jarayonlar uxlamasin.
    codes = [
        await _powercfg("/change", "standby-timeout-ac", str(minutes)),
        await _powercfg("/change", "standby-timeout-dc", str(minutes)),
        await _powercfg("/change", "hibernate-timeout-ac", str(minutes)),
        await _powercfg("/change", "hibernate-timeout-dc", str(minutes)),
    ]
    if any(c != 0 for c in codes):
        await message.answer(
            "⚠️ powercfg qisman xato qaytardi — kompyuterda qo'lda tekshiring: "
            "Sozlamalar → Tizim → Quvvat va uyqu."
        )
        return

    async with get_session() as session:
        await log_action(
            session,
            message.from_user.id,
            "power_sleep",
            "off" if minutes == 0 else f"on {minutes}min",
        )

    if minutes == 0:
        await message.answer(
            "🖥 ✅ Uyqu rejimi O'CHIRILDI — kompyuter endi uxlamaydi "
            "(ekran o'chishi mumkin, bu jarayonlarga ta'sir qilmaydi).\n\n"
            "⚠️ Eslatma: noutbuk QOPQOG'I yopilsa baribir uxlashi mumkin — "
            "buni faqat qo'lda sozlash kerak: Boshqaruv paneli → Quvvat → "
            "«Qopqoq yopilganda: hech narsa qilmaslik»."
        )
    else:
        await message.answer(
            f"🖥 💤 Uyqu rejimi QAYTARILDI — kompyuter {minutes} daqiqa "
            f"tegilmasa uxlaydi.\n\n⚠️ Diqqat: kompyuter uxlasa TIZIM HAM "
            f"TO'XTAYDI (mijozlar kuzatilmaydi). Sinov tugagandagina yoqing."
        )


@admin_router.message(Command("setreporttime"))
async def cmd_setreporttime(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """Kunlik hisobot vaqtini o'zgartirish (Toshkent, HH:MM) — superadmin.

    MUHIM: shunchaki sozlamani yozish yetmaydi — ochiq DAILY_REPORT ishining
    `due_at`i ham yangi vaqtga ko'chiriladi, aks holda o'zgarish faqat
    KEYINGI hisobotdan keyin kuchga kirardi.

    T-9 — ruxsat `permissions.COMMANDS["setreporttime"]` da (Owner + Rop).
    """
    if not command.args:
        async with get_session() as session:
            current = await get_daily_report_time(session)
        await message.answer(
            f"Joriy hisobot vaqti: <b>{current}</b> (Toshkent)\n\n"
            f"O'zgartirish: <code>/setreporttime 20:30</code>"
        )
        return

    async with get_session() as session:
        try:
            await set_daily_report_time(session, command.args)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        new_time = await get_daily_report_time(session)

        # Ochiq DAILY_REPORT ishini yangi vaqtga ko'chirish.
        result = await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.kind == JobKind.DAILY_REPORT,
                ScheduledJob.done_at.is_(None),
            )
        )
        new_due = next_daily_report_due_utc(datetime.datetime.utcnow(), new_time)
        jobs = result.scalars().all()
        for job in jobs:
            job.due_at = new_due
        if not jobs:
            session.add(ScheduledJob(kind=JobKind.DAILY_REPORT, due_at=new_due))
        await log_action(
            session, message.from_user.id, "set_report_time", new_time
        )
        await session.commit()

    local_due = new_due + datetime.timedelta(hours=5)
    await message.answer(
        f"✅ Kunlik hisobot vaqti: <b>{new_time}</b> (Toshkent).\n"
        f"Keyingi hisobot: {local_due:%d.%m.%Y %H:%M} da guruhga tushadi."
    )


@admin_router.message(Command("vstats"))
async def cmd_vstats(message: Message, current_admin: Admin) -> None:
    text, markup = await _build_vstats(current_admin, "d", "t")
    await message.answer(text, reply_markup=markup)


@admin_router.callback_query(F.data.startswith("vst:"))
async def cb_vstats(callback: CallbackQuery) -> None:
    current_admin = await _guard(callback)
    if current_admin is None:
        return

    # Format: vst:<davr>[:<ko'rinish>[:<admin_id>]] — eski `vst:d` ham qabul.
    parts = callback.data.split(":")
    period = parts[1] if len(parts) > 1 else "d"
    view = parts[2] if len(parts) > 2 else "t"
    target_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None

    text, markup = await _build_vstats(current_admin, period, view, target_id)
    await _edit(callback, text, markup)
    await callback.answer()


# --------------------------------------------------------------------------- #
# TZ v2 6-bo'lim (B-3) — tekshiruv dvigateli boshqaruvi
# --------------------------------------------------------------------------- #

_CHECK_CATEGORY_LABELS = {
    CheckCategory.CHECK_PASSED: "✅ O'TDI",
    CheckCategory.CHECK_FAILED: "❌ O'TMADI",
    CheckCategory.CHECK_ERROR: "⚠️ XATO",
}


def _parse_check_category(raw: str) -> CheckCategory | None:
    normalized = raw.strip().upper()
    aliases = {
        "PASSED": CheckCategory.CHECK_PASSED,
        "CHECK_PASSED": CheckCategory.CHECK_PASSED,
        "OTDI": CheckCategory.CHECK_PASSED,
        "FAILED": CheckCategory.CHECK_FAILED,
        "CHECK_FAILED": CheckCategory.CHECK_FAILED,
        "OTMADI": CheckCategory.CHECK_FAILED,
        "ERROR": CheckCategory.CHECK_ERROR,
        "CHECK_ERROR": CheckCategory.CHECK_ERROR,
        "XATO": CheckCategory.CHECK_ERROR,
    }
    return aliases.get(normalized)


@admin_router.message(Command("sessions"))
async def cmd_sessions(message: Message) -> None:
    """TZ v2 4.3 — har admin akkauntining sessiya holati.

    Rol tekshiruvi `RolePermission` middleware'da (`permissions.COMMANDS`
    jadvalidagi "sessions" yozuvi) — bu yerda takrorlanmaydi.
    """
    text = await _sessions_text()
    await message.answer(text)


async def _sessions_text() -> str:
    """Buyruq ham, "⚙️ Sozlamalar → 🔌 Sessiyalar" tugmasi ham shu matnni
    ko'rsatadi — ikki joyda ikki xil ko'rinish bo'lib qolmasligi uchun."""
    async with get_session() as session:
        rows = await list_admin_sessions(session)
    if not rows:
        return views.SESSIONS_EMPTY_TEXT
    return views.sessions_text(rows)


@admin_router.callback_query(F.data == "nav:sessions")
async def cb_sessions(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    await _edit(callback, await _sessions_text(), kb.back_to("nav:settings", "⬅️ Sozlamalar"))
    await callback.answer()


@admin_router.message(Command("setchecker"))
async def cmd_setchecker(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """TZ v2 6.3 — tekshiruvchi lichkani belgilash (username yoki raqamli id).

    T-9 — ruxsat `permissions.COMMANDS["setchecker"]` da (Owner + Dasturchi).
    """
    if not command.args:
        async with get_session() as session:
            current = await get_checker_account(session)
        await message.answer(
            f"Joriy tekshiruvchi: <code>{current or 'belgilanmagan'}</code>\n\n"
            f"Belgilash: <code>/setchecker &lt;username yoki id&gt;</code>\n\n"
            f"⚠️ Tekshiruvchi har bir admin akkauntidan xabar qabul qila "
            f"olishi kerak (kontaktga qo'shsin)."
        )
        return
    value = command.args.strip()
    async with get_session() as session:
        await set_checker_account(session, value)
        await log_action(session, message.from_user.id, "set_checker", value)
        # Tekshiruvchi ayni vaqtda kuzatilayotgan admin ham bo'lsa, unga
        # ketgan HAR BIR so'rov o'sha akkauntning o'z relay klienti tomonidan
        # qayta o'qiladi. Relay endi buni e'tiborsiz qoldiradi (T-5), lekin
        # konfiguratsiyaning o'zi baribir chalkash — shuning uchun ogohlantirish.
        clash = await _checker_is_watched_admin(session, value)

    text = f"✅ Tekshiruvchi belgilandi: <code>{value}</code>"
    if clash is not None:
        text += (
            f"\n\n⚠️ <b>DIQQAT:</b> bu akkaunt ayni vaqtda kuzatilayotgan "
            f"admin hamdir ({display_name(clash)}).\n"
            f"Tavsiya: tekshiruvchi uchun ALOHIDA akkaunt ishlating — aks "
            f"holda unga ketgan so'rovlar o'sha akkauntning o'z klienti "
            f"tomonidan qayta o'qiladi."
        )
    await message.answer(text)


async def _checker_is_watched_admin(session, value: str) -> Admin | None:
    """Tekshiruvchi sifatida ko'rsatilgan qiymat kuzatilayotgan adminmi.

    `value` ham `@username`, ham raqamli id bo'lishi mumkin — ikkovini ham
    tekshiramiz.
    """
    needle = value.strip().lstrip("@").lower()
    for admin in await list_admins(session):
        if not admin.is_active:
            continue
        if needle == str(admin.tg_user_id):
            return admin
        if admin.tg_username and needle == admin.tg_username.lower():
            return admin
    return None


@admin_router.message(Command("checkpatterns"))
async def cmd_checkpatterns(message: Message) -> None:
    """TZ v2 6.4 — tanish shablonlari ro'yxati (uch kategoriya)."""
    async with get_session() as session:
        patterns = await get_all_patterns(session)
    blocks = []
    for category in CheckCategory:
        items = patterns[category]
        body = (
            "\n".join(f"  {i}. <code>{p}</code>" for i, p in enumerate(items, 1))
            if items
            else "  ❌ kiritilmagan"
        )
        blocks.append(f"<b>{_CHECK_CATEGORY_LABELS[category]}</b> ({category.value})\n{body}")
    await message.answer(
        "🔎 <b>Tekshiruvchi javobini tanish shablonlari</b>\n\n"
        + "\n\n".join(blocks)
        + "\n\nQo'shish: <code>/addcheckpattern OTDI bor</code>\n"
        "O'chirish: <code>/delcheckpattern OTDI 1</code>\n"
        "Sinash: <code>/testcheck bazada bor emas</code>\n"
        "Formatlar: oddiy so'z · <code>~ichida</code> · <code>=aynan</code> · "
        "<code>re:regex</code>"
    )


@admin_router.message(Command("addcheckpattern"))
async def cmd_addcheckpattern(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    # Audit — TZ v2 §10: sozlash huquqi superadminda. Shablonlar mijozga
    # ketadigan natijani belgilaydi — oddiy admin o'zgartira olmasligi kerak.
    # T-9 — tekshiruvning o'zi `permissions.COMMANDS["addcheckpattern"]` da.
    parts = (command.args or "").split(maxsplit=1)
    category = _parse_check_category(parts[0]) if parts else None
    if category is None or len(parts) < 2:
        await message.answer(
            "Format: <code>/addcheckpattern &lt;OTDI|OTMADI|XATO&gt; &lt;shablon&gt;</code>"
        )
        return
    async with get_session() as session:
        try:
            await add_pattern(session, category, parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await log_action(
            session, message.from_user.id, "add_check_pattern",
            f"{category.value}: {parts[1]}",
        )
    await message.answer(
        f"✅ {_CHECK_CATEGORY_LABELS[category]} ro'yxatiga qo'shildi: "
        f"<code>{parts[1]}</code>"
    )


@admin_router.message(Command("delcheckpattern"))
async def cmd_delcheckpattern(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    # T-9 — ruxsat `permissions.COMMANDS["delcheckpattern"]` da.
    parts = (command.args or "").split()
    category = _parse_check_category(parts[0]) if parts else None
    if category is None or len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Format: <code>/delcheckpattern &lt;OTDI|OTMADI|XATO&gt; &lt;raqam&gt;</code> "
            "(raqamni /checkpatterns ro'yxatidan oling)"
        )
        return
    async with get_session() as session:
        removed = await remove_pattern(session, category, int(parts[1]))
        if removed is None:
            await message.answer("Bunday raqamli shablon topilmadi.")
            return
        await log_action(
            session, message.from_user.id, "del_check_pattern",
            f"{category.value}: {removed}",
        )
    await message.answer(f"🗑 O'chirildi: <code>{removed}</code>")


@admin_router.message(Command("testcheck"))
async def cmd_testcheck(message: Message, command: CommandObject) -> None:
    """TZ v2 6.4.6 — sinov: berilgan matn qanday tanib olinishini ko'rsatadi.
    Jonli ishga tushirishdan oldin haqiqiy javoblarni shu yerda tekshiring."""
    if not command.args:
        await message.answer("Format: <code>/testcheck &lt;javob matni&gt;</code>")
        return
    async with get_session() as session:
        patterns = await get_all_patterns(session)
    try:
        category = classify(command.args, patterns)
    except AmbiguousMatch:
        await message.answer(
            "⚠️ <b>QARAMA-QARSHI</b> — matn ham O'TDI, ham O'TMADI shabloniga "
            "alohida joylarda mos keldi. Jonli rejimda bu NEEDS_ADMIN bo'ladi."
        )
        return
    if category is None:
        await message.answer(
            "❓ <b>Tanilmadi</b> — hech qaysi shablonga mos emas. Jonli rejimda "
            "tizim keyingi xabarni kutadi (stall taymerigacha)."
        )
        return
    await message.answer(
        f"{_CHECK_CATEGORY_LABELS[category]} deb tanildi ({category.value})."
    )


@admin_router.message(Command("shadow"))
async def cmd_shadow(
    message: Message, command: CommandObject, current_admin: Admin
) -> None:
    """TZ v2 6.4.6 — soya rejimi.

    ARGUMENTSIZ `/shadow` faqat HOLATNI ko'rsatadi. Avval u rejimni
    almashtirardi — jonli sinovda admin holatni bilmoqchi bo'lib yozgan
    buyruq xavfsizlik tormozini jimgina ochib yubordi (2 marta sodir
    bo'ldi). O'zgartirish endi faqat aniq `on`/`off` argumenti bilan
    (`/setreporttime` bilan bir xil mantiq: argumentsiz — ko'rsatadi,
    argument bilan — o'zgartiradi).
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

    # T-9 — rol tekshiruvi `permissions.COMMANDS["shadow"]` da (Owner +
    # Dasturchi); bu yerdagi nusxa olib tashlandi.
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
        # Soya rejimi o'chirilganda tanish shablonlari holatini ANIQ aytamiz.
        # Jonli sinovda (K-3) shablonlar to'liq emasligi sababli salbiy javob
        # "O'TDI" deb tanilgan edi; soya rejimi o'chgan zahoti bunday xato
        # to'g'ridan-to'g'ri mijozga ketadi. Avval bu yerda faqat umumiy
        # "ishonch hosil qiling" eslatmasi bor edi — endi qaysi kategoriya
        # bo'shligi nomma-nom ko'rsatiladi.
        bosh_kategoriyalar = [] if new_value else await missing_categories(session)

    if new_value:
        await message.answer(
            "🕶 Soya rejimi <b>YOQILDI</b> — tizim taniydi, bazaga yozadi, "
            "lekin mijozga HECH NARSA yozmaydi."
        )
        return

    matn = (
        "🟢 Soya rejimi <b>O'CHIRILDI</b> — natijalar endi mijozlarga "
        "yetkaziladi.\n\n"
    )
    if bosh_kategoriyalar:
        royxat = "\n".join(
            f"  • {_CHECK_CATEGORY_LABELS[c]} (<code>{c.value}</code>)"
            for c in bosh_kategoriyalar
        )
        matn += (
            f"🚨 <b>DIQQAT: quyidagi kategoriyada birorta ham shablon yo'q:</b>\n"
            f"{royxat}\n\n"
            f"Bu holatda tekshiruvchining javobi noto'g'ri tanilishi mumkin — "
            f"masalan \"bazada bor emas\" javobi <b>O'TDI</b> deb o'qilib, "
            f"ovozi o'tmagan mijozga \"tasdiqlandi\" deb yoziladi.\n\n"
            f"Tavsiya: <code>/shadow on</code> bilan qaytaring, so'ng "
            f"<code>/addcheckpattern</code> bilan to'ldiring va "
            f"<code>/testcheck &lt;matn&gt;</code> bilan sinab ko'ring."
        )
    else:
        matn += (
            "Uchala kategoriyada shablon bor. Baribir "
            "<code>/testcheck &lt;matn&gt;</code> bilan tekshiruvchi yozadigan "
            "haqiqiy variantlarni sinab ko'ring — noto'g'ri tanilgan javob "
            "endi to'g'ridan-to'g'ri mijozga ketadi."
        )
    await message.answer(matn)


@admin_router.message(Command("unrecognized"))
async def cmd_unrecognized(message: Message) -> None:
    """TZ v2 6.4.6 — tanilmagan javoblar jurnali. Tugma bosilsa o'sha matn
    shablonga avtomatik qo'shiladi — shablonlar haqiqiy trafikdan o'sadi."""
    async with get_session() as session:
        result = await session.execute(
            select(CheckRequest)
            .where(
                CheckRequest.raw_reply != "",
                (CheckRequest.result == CheckResult.UNRECOGNIZED)
                | (CheckRequest.replied_at.is_(None) & CheckRequest.sent_at.is_not(None)),
            )
            .order_by(CheckRequest.id.desc())
            .limit(10)
        )
        requests = result.scalars().all()
    if not requests:
        await message.answer("Tanilmagan javoblar yo'q. 👍")
        return
    for req in requests:
        last_line = req.raw_reply.strip().splitlines()[-1][:200]
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ O'TDI", callback_data=f"ucp:{req.id}:PASSED"
                    ),
                    InlineKeyboardButton(
                        text="❌ O'TMADI", callback_data=f"ucp:{req.id}:FAILED"
                    ),
                    InlineKeyboardButton(
                        text="⚠️ XATO", callback_data=f"ucp:{req.id}:ERROR"
                    ),
                ]
            ]
        )
        await message.answer(
            f"❓ So'rov #{req.id} · {req.phone}\n"
            f"Javob: <code>{last_line}</code>\n\n"
            f"Bu javob qaysi ma'noda? (bosilsa shablonga qo'shiladi)",
            reply_markup=markup,
        )


@admin_router.callback_query(F.data.startswith("vres:"))
async def cb_failed_result(callback: CallbackQuery) -> None:
    """TZ v2 7.1 — FAILED natija tasdiqlash tugmalari.

    Adminbot Telethon'ga ega emas — [Mijozga yuborish] bosilganda
    `scheduled_jobs`ga NOTIFY_FAILED ishi yoziladi, uni Teleton polleri
    30 soniya ichida olib, mijozga o'sha adminning akkauntidan yozadi
    (v1 dagi bayroq naqshining scheduled_jobs varianti).
    """
    if await _guard(callback) is None:
        return
    _, raw_id, action = callback.data.split(":")
    request_id = int(raw_id)

    async with get_session() as session:
        req = await session.get(CheckRequest, request_id)
        if req is None:
            await callback.answer("So'rov topilmadi.", show_alert=True)
            return
        if req.customer_notified_at is not None:
            await _edit(callback, "Bu natija mijozga allaqachon yuborilgan.")
            await callback.answer()
            return

        if action == "send":
            session.add(
                ScheduledJob(
                    kind=JobKind.NOTIFY_FAILED,
                    case_id=req.case_id,
                    due_at=datetime.datetime.utcnow(),
                    payload=json.dumps({"request_id": request_id}),
                )
            )
            await log_action(
                session,
                callback.from_user.id,
                "confirm_failed_notify",
                f"request #{request_id}",
            )
            await session.commit()
            await _edit(
                callback,
                "📤 Yuborish tasdiqlandi — mijozga 1 daqiqa ichida "
                "\"o'tmadi\" xabari boradi (admin akkauntidan).",
            )
        else:
            await log_action(
                session,
                callback.from_user.id,
                "skip_failed_notify",
                f"request #{request_id}",
            )
            await session.commit()
            await _edit(
                callback,
                "✋ Yuborilmadi — mijoz bilan o'zingiz gaplashasiz "
                "(natija bazada saqlangan).",
            )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("ucp:"))
async def cb_unrecognized_classify(callback: CallbackQuery) -> None:
    current_admin = await _guard(callback)
    if current_admin is None:
        return
    # Audit — tugma ham shablonga yozadi: superadmin huquqi (TZ v2 §10).
    # T-9 — tekshiruvni `RolePermission` bajaradi (`CALLBACKS["ucp"]`).
    _, raw_id, raw_cat = callback.data.split(":")
    category = _parse_check_category(raw_cat)
    async with get_session() as session:
        req = await session.get(CheckRequest, int(raw_id))
        if req is None or category is None or not req.raw_reply.strip():
            await callback.answer("So'rov topilmadi.", show_alert=True)
            return
        last_line = req.raw_reply.strip().splitlines()[-1]
        # Aynan-tenglik shabloni sifatida qo'shiladi (eng xavfsiz variant —
        # keng qamrovli so'z emas, aynan shu javob matni).
        await add_pattern(session, category, f"={last_line}")
        await log_action(
            session,
            callback.from_user.id,
            "classify_unrecognized",
            f"req #{req.id} -> {category.value}",
        )
    await _edit(
        callback,
        f"✅ Shablon qo'shildi: <code>={last_line[:100]}</code> → "
        f"{_CHECK_CATEGORY_LABELS[category]}",
    )
    await callback.answer("Shablon qo'shildi.")


# --------------------------------------------------------------------------- #
# Admin tushunarsiz narsa yozsa — menyuni ko'rsatamiz.
#
# Bu handler admin_router'ning ENG OXIRIDA turishi shart: aks holda u
# yuqoridagi handler'larni to'sib qo'yadi. Shu bilan birga adminning oddiy
# matni pastdagi `fallback_router`gacha yetib bormaydi — aks holda admin
# "Sizda ruxsat yo'q" degan noto'g'ri javob olardi.
# --------------------------------------------------------------------------- #


@admin_router.message()
async def on_unknown(message: Message, current_admin: Admin) -> None:
    await message.answer(
        "Tushunmadim 🤔\n\nPastdagi menyudan bo'limni tanlang, yoki qidirish "
        "uchun nomerni yuboring.",
        reply_markup=kb.main_menu(current_admin),
    )


# --------------------------------------------------------------------------- #
# Ruxsatsiz foydalanuvchilar (TZ 12.2 — boshqa hech kim emas)
# --------------------------------------------------------------------------- #


@fallback_router.message()
async def cmd_denied(message: Message) -> None:
    await message.answer("Sizda ruxsat yo'q.")


@fallback_router.callback_query()
async def cb_denied(callback: CallbackQuery) -> None:
    await callback.answer("Sizda ruxsat yo'q.", show_alert=True)


async def main() -> None:
    # T-16 — log sozlash aynan shu yerda (modul darajasida emas): faqat
    # xizmat HAQIQATAN ishga tushganda jonli log fayli ochiladi.
    configure_logging("adminbot")

    bot = Bot(
        token=settings.adminbot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(fallback_router)

    await init_db()
    async with get_session() as session:
        await ensure_admins_seeded(session, settings.admin_tg_ids)
        await ensure_templates_seeded(session)

    log.info("Adminbot ishga tushdi (tugmali interfeys).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
