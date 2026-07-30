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

Ataylab yo'q: rol bo'linishi (owner/rop/admin/viewer, TZ 14-bo'lim — "loyiha
to'liq oydinlashgach hal qilinadi"). Hozircha ro'yxatdagi HAR BIR admin
hammasini ko'radi (Q51'dagi ko'rish cheklovi rollar aniqlashgach qo'shiladi).
"""

import asyncio
import logging

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select

from adminbot_service import keyboards as kb
from adminbot_service import views
from adminbot_service.states import (
    AddBotFlow,
    EditPatternFlow,
    EditTemplateFlow,
    SearchFlow,
    UserNoteFlow,
)
from core.config import settings
from core.db import get_session, init_db
from core.enums import CaseStatus
from core.logic.admins import ensure_admins_seeded, is_admin
from core.logic.audit import list_recent, log_action
from core.logic.bot_patterns import (
    REQUIRED_KEYS as BOT_PATTERN_KEYS,
    list_patterns as list_bot_patterns,
    missing_patterns,
    set_pattern as set_bot_pattern,
)
from core.logic.bot_pool import (
    PHONE_FORMATS,
    BotPoolManager,
    add_bot,
    get_bot,
    list_bots,
    set_bot_active,
    set_bot_phone_format,
)
from core.logic.case_admin import (
    get_case_bundle,
    list_cases_by_statuses,
    manual_confirm,
    manual_reject,
    request_redispatch,
    set_user_blocked,
    set_user_note,
    set_user_safe,
)
from core.logic.customers import cases_for_user
from core.logic.logging_setup import configure_logging
from core.logic.phone import extract_phone
from core.logic.settings_store import is_verbose, set_verbose
from core.logic.stats import gather_stats
from core.logic.templates import DEFAULTS, ensure_templates_seeded, get_template, list_templates, set_template
from core.models import Case, CouponAttempt, User

configure_logging("adminbot")
log = logging.getLogger("adminbot")

PROBLEM_STATUSES = [
    CaseStatus.DUPLICATE_ACTIVE,
    CaseStatus.NEEDS_ADMIN,
    CaseStatus.SUSPICIOUS_HOLD,
    CaseStatus.TIMEOUT,
]


class IsAdmin(BaseFilter):
    """TZ 12.2 — faqat `admins` jadvalidagi Telegram ID-lar buyruq bera oladi."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        async with get_session() as session:
            return await is_admin(session, message.from_user.id)


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


async def _guard(callback: CallbackQuery) -> bool:
    """Inline tugma bosgan odam haqiqatan adminmi (TZ 12.2)."""
    if callback.from_user is None:
        return False
    async with get_session() as session:
        if not await is_admin(session, callback.from_user.id):
            await callback.answer("Sizda ruxsat yo'q.", show_alert=True)
            return False
    return True


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
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        views.welcome(message.from_user.first_name if message.from_user else None),
        reply_markup=kb.main_menu(),
    )


@admin_router.message(Command("help"))
@admin_router.message(F.text == kb.BTN_HELP)
async def show_help(message: Message) -> None:
    await message.answer(views.HELP_TEXT, reply_markup=kb.main_menu())


@admin_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@admin_router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(callback, "Bekor qilindi.")
    await callback.answer()


# --------------------------------------------------------------------------- #
# Statistika (TZ 10-bo'lim)
# --------------------------------------------------------------------------- #


@admin_router.message(Command("stats"))
@admin_router.message(F.text == kb.BTN_STATS)
async def show_stats(message: Message) -> None:
    async with get_session() as session:
        stats = await gather_stats(session)
    await message.answer(views.stats_text(stats))


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
    """TZ 12 — osilib qolgan botni majburan bo'shatish (lane leak oldini olish)."""
    if not await _guard(callback):
        return
    bot_id = int(callback.data.split(":")[1])

    async with get_session() as session:
        bot = await get_bot(session, bot_id)
        if bot is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return
        # Adminbot'da pool navbati yo'q (u Teleton xotirasida) — shuning uchun
        # faqat DB'dagi band-lik bayrog'i tozalanadi, navbat Teleton tomonida
        # o'z holicha davom etadi.
        await BotPoolManager().release(session, bot_id)
        await log_action(session, callback.from_user.id, "bot_force_free", f"@{bot.username}")
        bot = await get_bot(session, bot_id)
        text, markup = views.bot_card(bot), kb.bot_card(bot)

    await _edit(callback, text, markup)
    await callback.answer("Bot bo'shatildi.")


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


async def _case_page(kind: str, page: int):
    statuses = PROBLEM_STATUSES if kind == "pr" else [CaseStatus.NUMBER_RECEIVED]
    async with get_session() as session:
        cases = await list_cases_by_statuses(session, statuses, limit=200)
    total = len(cases)
    start = page * kb.PAGE_SIZE
    return cases[start : start + kb.PAGE_SIZE], total


@admin_router.message(Command("problems"))
@admin_router.message(F.text == kb.BTN_PROBLEMS)
async def show_problems(message: Message) -> None:
    page_items, total = await _case_page("pr", 0)
    await message.answer(
        views.case_list_text("pr", total), reply_markup=kb.case_list(page_items, "pr", 0, total)
    )


@admin_router.message(Command("pending"))
@admin_router.message(F.text == kb.BTN_PENDING)
async def show_pending(message: Message) -> None:
    page_items, total = await _case_page("pn", 0)
    await message.answer(
        views.case_list_text("pn", total), reply_markup=kb.case_list(page_items, "pn", 0, total)
    )


@admin_router.callback_query(F.data.regexp(r"^nav:(problems|pending)$"))
async def cb_case_list_root(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    kind = "pr" if callback.data.endswith("problems") else "pn"
    page_items, total = await _case_page(kind, 0)
    await _edit(
        callback, views.case_list_text(kind, total), kb.case_list(page_items, kind, 0, total)
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^pg:(pr|pn):\d+$"))
async def cb_case_page(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, kind, raw_page = callback.data.split(":")
    page = int(raw_page)
    page_items, total = await _case_page(kind, page)
    await _edit(
        callback, views.case_list_text(kind, total), kb.case_list(page_items, kind, page, total)
    )
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^cs:\d+$"))
async def cb_case_card(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    case_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        bundle = await get_case_bundle(session, case_id)
        if bundle is None:
            await callback.answer("Murojaat topilmadi.", show_alert=True)
            return
        case, user, attempts = bundle
        text, markup = views.case_card(case, user, attempts), kb.case_card(case, user)
    await _edit(callback, text, markup)
    await callback.answer()


# --------------------------------------------------------------------------- #
# TZ 9.3 — "Noaniq natijada: [Tasdiqlash] [Rad] [Qayta uzatish]"
# --------------------------------------------------------------------------- #


@admin_router.callback_query(F.data.regexp(r"^cs:\d+:(ok|no|again)$"))
async def cb_case_resolve(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, raw_id, action = callback.data.split(":")
    case_id = int(raw_id)

    async with get_session() as session:
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


@admin_router.callback_query(F.data.regexp(r"^usr:\d+$"))
async def cb_user_card(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    user_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
        cases = await cases_for_user(session, user_id)
        text, markup = views.user_card(user, cases), kb.user_card(user)
    await _edit(callback, text, markup)
    await callback.answer()


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:(block|unblock|safe)$"))
async def cb_user_flag(callback: CallbackQuery) -> None:
    if not await _guard(callback):
        return
    _, raw_id, action = callback.data.split(":")
    user_id = int(raw_id)

    async with get_session() as session:
        if action == "block":
            user = await set_user_blocked(session, user_id, True)
            label, note = "block_user", "Bloklandi."
        elif action == "unblock":
            user = await set_user_blocked(session, user_id, False)
            label, note = "unblock_user", "Blokdan chiqarildi."
        else:
            user = await set_user_safe(session, user_id, True)
            label, note = "mark_safe", "Xavfsiz deb belgilandi."

        if user is None:
            await callback.answer("Mijoz topilmadi.", show_alert=True)
            return
        await log_action(session, callback.from_user.id, label, f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text, markup = views.user_card(user, cases), kb.user_card(user)

    await _edit(callback, text, markup)
    await callback.answer(note)


@admin_router.callback_query(F.data.regexp(r"^usr:\d+:note$"))
async def cb_user_note(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(callback):
        return
    user_id = int(callback.data.split(":")[1])
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
async def on_user_note(message: Message, state: FSMContext) -> None:
    note = (message.text or "").strip()
    if not note:
        await message.answer("Izoh bo'sh. Qayta yuboring.")
        return
    user_id = (await state.get_data())["user_id"]
    await state.clear()

    async with get_session() as session:
        user = await set_user_note(session, user_id, note)
        if user is None:
            await message.answer("Mijoz topilmadi.")
            return
        await log_action(session, message.from_user.id, "user_note", f"user #{user_id}")
        cases = await cases_for_user(session, user_id)
        text, markup = views.user_card(user, cases), kb.user_card(user)

    await message.answer(text, reply_markup=markup)


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
async def on_search_phone(message: Message, state: FSMContext) -> None:
    phone = extract_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Nomer tanilmadi. O'zbekiston formatida yuboring (masalan 998901234567)."
        )
        return
    await state.clear()
    await _send_search_results(message, phone)


@admin_router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
    async with get_session() as session:
        entries = await list_recent(session, limit=20)
    await message.answer(views.audit_text(entries))


@admin_router.message(F.text.func(lambda t: t and t.lower().startswith("drop find")))
async def cmd_drop_find(message: Message) -> None:
    raw = message.text[len("drop find") :].strip()
    phone = extract_phone(raw) if raw else None
    if phone is None:
        await message.answer(
            "Format: <code>drop find &lt;nomer&gt;</code>\n"
            "Yoki menyudagi 🔍 <b>Nomer qidirish</b> tugmasidan foydalaning."
        )
        return
    await _send_search_results(message, phone)


@admin_router.message(
    ~F.text.startswith("/"),
    F.text.func(lambda t: t and extract_phone(t) is not None),
)
async def on_bare_phone(message: Message) -> None:
    """Admin shunchaki nomer yuborsa — darhol qidiruv (qulaylik uchun).

    Buyruqlar ataylab chetlab o'tiladi: `/settemplate CONFIRMED ... 998901234567 ...`
    kabi ichida nomer bo'lgan buyruq bu handler'ga tushib ketmasligi kerak
    (u ro'yxatda buyruq handler'laridan oldin turadi).
    """
    await _send_search_results(message, extract_phone(message.text))


async def _send_search_results(message: Message, phone: str) -> None:
    async with get_session() as session:
        cases = (
            await session.execute(select(Case).where(Case.phone == phone).order_by(Case.id.desc()))
        ).scalars().all()

    if not cases:
        await message.answer(f"<code>{phone}</code> bo'yicha murojaat topilmadi.")
        return

    header = f"🔍 <code>{phone}</code> — {len(cases)} ta murojaat:"
    await message.answer(header, reply_markup=kb.case_list(list(cases)[: kb.PAGE_SIZE], "pr", 0, 0))


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
    await _edit(
        callback,
        views.health_text(bots, missing, settings.use_real_verification_bots),
        kb.back_to("nav:settings", "⬅️ Sozlamalar"),
    )
    await callback.answer()


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
# Admin tushunarsiz narsa yozsa — menyuni ko'rsatamiz.
#
# Bu handler admin_router'ning ENG OXIRIDA turishi shart: aks holda u
# yuqoridagi handler'larni to'sib qo'yadi. Shu bilan birga adminning oddiy
# matni pastdagi `fallback_router`gacha yetib bormaydi — aks holda admin
# "Sizda ruxsat yo'q" degan noto'g'ri javob olardi.
# --------------------------------------------------------------------------- #


@admin_router.message()
async def on_unknown(message: Message) -> None:
    await message.answer(
        "Tushunmadim 🤔\n\nPastdagi menyudan bo'limni tanlang, yoki qidirish "
        "uchun nomerni yuboring.",
        reply_markup=kb.main_menu(),
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
