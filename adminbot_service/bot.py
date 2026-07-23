"""Adminbot (aiogram 3.x) — TZ 9-bo'lim.

MVP-2: bildirishnoma, `drop find`, shablon sozlash (`/templates`,
`/settemplate`), bot qo'shish (`/addbot`, `/bots`), navbat/muammo ko'rinishlari
(`/pending`, `/problems`). MVP-3: shubhali-holat Xavfsiz/Bloklash inline
tugmalari. MVP-4: statistika (`/stats`, TZ 10-bo'lim), admin harakatlari
tarixi (`/audit`, `core/logic/audit.py`, TZ 11.5/12.2).

MVP-5: bot-tanish shablonlari (`/botpatterns`, `/setbotpattern`, TZ 7.1, 9.4
Q16), `/addbot`ga ixtiyoriy "start" bayrog'i (Q54).

Ataylab yo'q: rol bo'linishi (owner/rop/admin/viewer, TZ 14-bo'lim — "loyiha
to'liq oydinlashgach hal qilinadi"). Hozircha ro'yxatdagi HAR BIR admin
hammasini ko'radi (Q51'dagi ko'rish cheklovi rollar aniqlashgach qo'shiladi).
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from core.config import settings
from core.db import get_session, init_db
from core.logic.admins import ensure_admins_seeded, is_admin
from core.logic.audit import list_recent, log_action
from core.logic.bot_patterns import REQUIRED_KEYS as BOT_PATTERN_KEYS, list_patterns as list_bot_patterns, set_pattern as set_bot_pattern
from core.logic.bot_pool import add_bot, list_bots
from core.logic.logging_setup import configure_logging
from core.logic.phone import extract_phone
from core.logic.settings_store import is_verbose, set_verbose
from core.logic.stats import gather_stats
from core.logic.templates import DEFAULTS, ensure_templates_seeded, list_templates, set_template
from core.enums import CaseStatus
from core.models import Case, CouponAttempt, User

configure_logging("adminbot")
log = logging.getLogger("adminbot")


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


HELP_TEXT = (
    "Buyruqlar:\n"
    "/bots — tekshiruv botlari holati\n"
    "/addbot <username> [format] [start] — yangi bot qo'shish\n"
    "/templates — mijozga yuboriladigan shablonlar\n"
    "/settemplate <KEY> <matn> — shablonni o'zgartirish\n"
    "/botpatterns — bot-TANISH shablonlarini ko'rish (mijozga yuborilmaydi)\n"
    "/setbotpattern <KEY> <matn> — bot-tanish shablonini o'zgartirish\n"
    "/notify — bildirishnoma rejimini ko'rish/o'zgartirish\n"
    "/pending — navbatda turgan murojaatlar\n"
    "/problems — e'tibor talab qiladigan murojaatlar\n"
    "/stats — statistika\n"
    "/audit — so'nggi admin harakatlari\n"
    "drop find <nomer> — nomer bo'yicha holatni ko'rish"
)


@admin_router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer("Assalomu alaykum! Siz ro'yxatdagi adminsiz.\n\n" + HELP_TEXT)


@admin_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


# --------------------------------------------------------------------------- #
# /bots, /addbot — TZ 3.3, 9.5
# --------------------------------------------------------------------------- #


@admin_router.message(Command("bots"))
async def cmd_bots(message: Message) -> None:
    async with get_session() as session:
        bots = await list_bots(session)

    if not bots:
        await message.answer("Hali birorta tekshiruv bot qo'shilmagan. /addbot bilan qo'shing.")
        return

    lines = []
    for bot in bots:
        holat = "band" if bot.is_busy else "bo'sh"
        faollik = "faol" if bot.is_active else "o'chirilgan"
        lines.append(
            f"#{bot.id} @{bot.username} — {holat}, {faollik}, format: {bot.phone_format}, "
            f"jami ishlangan: {bot.total_processed}, joriy case: {bot.current_case_id or '—'}"
        )
    await message.answer("\n".join(lines))


@admin_router.message(Command("addbot"))
async def cmd_addbot(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Format: /addbot <username> [nomer_formati] [start]")
        return

    parts = command.args.split()
    needs_start = False
    if parts and parts[-1].lower() == "start":
        needs_start = True
        parts = parts[:-1]

    if not parts:
        await message.answer("Format: /addbot <username> [nomer_formati] [start]")
        return

    username = parts[0]
    phone_format = parts[1] if len(parts) > 1 else "+998XXXXXXXXX"

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

    start_note = " — avval /start yuboriladi (Q54)" if bot.needs_start_greeting else ""
    await message.answer(f"Qo'shildi: #{bot.id} @{bot.username} (format: {bot.phone_format}){start_note}.")


# --------------------------------------------------------------------------- #
# /templates, /settemplate — TZ 7.2, 9.2
# --------------------------------------------------------------------------- #


@admin_router.message(Command("templates"))
async def cmd_templates(message: Message) -> None:
    async with get_session() as session:
        values = await list_templates(session)

    lines = [f"{key}:\n{value}\n" for key, value in values.items()]
    await message.answer("\n".join(lines) + "\nO'zgartirish: /settemplate <KEY> <matn>")


@admin_router.message(Command("settemplate"))
async def cmd_settemplate(message: Message, command: CommandObject) -> None:
    if not command.args:
        keys = ", ".join(DEFAULTS.keys())
        await message.answer(f"Format: /settemplate <KEY> <matn>\nKalitlar: {keys}")
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Matn kiritilmadi. Format: /settemplate <KEY> <matn>")
        return

    key, value = parts[0].upper(), parts[1]
    if key not in DEFAULTS:
        keys = ", ".join(DEFAULTS.keys())
        await message.answer(f"Noma'lum kalit: {key}\nKalitlar: {keys}")
        return

    async with get_session() as session:
        await set_template(session, key, value)
        await log_action(session, message.from_user.id, "settemplate", f"{key} -> {value}")
    await message.answer(f"{key} yangilandi:\n{value}")


# --------------------------------------------------------------------------- #
# /botpatterns, /setbotpattern — TZ 7.1, 9.4 (Q16)
# --------------------------------------------------------------------------- #
#
# DIQQAT: bular mijozga yuborilmaydi (TZ 7-bo'lim, Q47 — ikki xil to'plam
# alohida). Bular tekshiruv botning O'Z chiqishini tanish uchun. Real bot
# rejimi (`USE_REAL_VERIFICATION_BOTS=true`) shu 4 tasi to'liq kiritilmaguncha
# ishga tushmaydi (Q16).


@admin_router.message(Command("botpatterns"))
async def cmd_botpatterns(message: Message) -> None:
    async with get_session() as session:
        patterns = await list_bot_patterns(session)

    lines = [f"{key}:\n{patterns.get(key) or '❌ KIRITILMAGAN'}\n" for key in BOT_PATTERN_KEYS]
    await message.answer(
        "Bot-TANISH shablonlari (mijozga yuborilmaydi, TZ 7.1):\n\n"
        + "\n".join(lines)
        + "\nO'zgartirish: /setbotpattern <KEY> <matn>"
    )


@admin_router.message(Command("setbotpattern"))
async def cmd_setbotpattern(message: Message, command: CommandObject) -> None:
    if not command.args:
        keys = ", ".join(BOT_PATTERN_KEYS)
        await message.answer(f"Format: /setbotpattern <KEY> <matn>\nKalitlar: {keys}")
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Matn kiritilmadi. Format: /setbotpattern <KEY> <matn>")
        return

    key, value = parts[0].upper(), parts[1]
    if key not in BOT_PATTERN_KEYS:
        keys = ", ".join(BOT_PATTERN_KEYS)
        await message.answer(f"Noma'lum kalit: {key}\nKalitlar: {keys}")
        return

    async with get_session() as session:
        await set_bot_pattern(session, key, value)
        await log_action(session, message.from_user.id, "setbotpattern", f"{key} -> {value}")
    await message.answer(f"{key} yangilandi:\n{value}")


# --------------------------------------------------------------------------- #
# /notify — TZ 9.1
# --------------------------------------------------------------------------- #


def _notify_keyboard(verbose: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if not verbose else "") + "Oddiy (faqat muhim)",
                    callback_data="notify:off",
                ),
                InlineKeyboardButton(
                    text=("✅ " if verbose else "") + "Batafsil (hammasi)",
                    callback_data="notify:on",
                ),
            ]
        ]
    )


@admin_router.message(Command("notify"))
async def cmd_notify(message: Message) -> None:
    async with get_session() as session:
        verbose = await is_verbose(session)
    await message.answer(
        "Joriy bildirishnoma rejimi: " + ("batafsil" if verbose else "oddiy (faqat muhim)"),
        reply_markup=_notify_keyboard(verbose),
    )


@admin_router.callback_query(F.data.startswith("notify:"))
async def cb_notify_toggle(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    async with get_session() as session:
        if not await is_admin(session, callback.from_user.id):
            await callback.answer("Sizda ruxsat yo'q.", show_alert=True)
            return
        verbose = callback.data == "notify:on"
        await set_verbose(session, verbose)
        await log_action(
            session, callback.from_user.id, "notify_toggle", "batafsil" if verbose else "oddiy"
        )

    await callback.message.edit_text(
        "Joriy bildirishnoma rejimi: " + ("batafsil" if verbose else "oddiy (faqat muhim)"),
        reply_markup=_notify_keyboard(verbose),
    )
    await callback.answer("Saqlandi.")


# --------------------------------------------------------------------------- #
# /pending, /problems — navbat va e'tibor talab qiladigan case'lar
# --------------------------------------------------------------------------- #


@admin_router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    # Bot topilmaguncha case NUMBER_RECEIVED holatida navbatda qoladi (TZ 3.1, Q45).
    async with get_session() as session:
        result = await session.execute(
            select(Case).where(Case.status == CaseStatus.NUMBER_RECEIVED).order_by(Case.id)
        )
        cases = result.scalars().all()

    if not cases:
        await message.answer("Navbatda hech kim yo'q.")
        return

    lines = [f"#{c.id} — {c.phone} — {c.created_at}" for c in cases]
    await message.answer("Navbatdagi murojaatlar:\n" + "\n".join(lines))


@admin_router.message(Command("problems"))
async def cmd_problems(message: Message) -> None:
    # TZ 2.3 (DUPLICATE_ACTIVE), 2.1/Q59 (NEEDS_ADMIN), 5.2 (SUSPICIOUS_HOLD).
    async with get_session() as session:
        result = await session.execute(
            select(Case)
            .where(
                Case.status.in_(
                    [CaseStatus.DUPLICATE_ACTIVE, CaseStatus.NEEDS_ADMIN, CaseStatus.SUSPICIOUS_HOLD]
                )
            )
            .order_by(Case.id)
        )
        cases = result.scalars().all()

    if not cases:
        await message.answer("Hozircha muammoli murojaat yo'q.")
        return

    lines = [
        f"#{c.id} — {c.status.value} — {c.phone} — user_id={c.user_id} — {c.created_at}"
        for c in cases
    ]
    await message.answer("Admin e'tiborini talab qiladigan murojaatlar:\n" + "\n".join(lines))


# --------------------------------------------------------------------------- #
# /stats, /audit — TZ 10-bo'lim, 11.5/12.2
# --------------------------------------------------------------------------- #


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    async with get_session() as session:
        stats = await gather_stats(session)

    status_lines = "\n".join(f"  {status}: {count}" for status, count in stats.by_status.items())
    await message.answer(
        "📊 Statistika\n\n"
        f"Bugungi murojaatlar: {stats.today_count}\n"
        f"Muammoli holatlar (joriy ochiq): {stats.problem_count}\n\n"
        f"Holat bo'yicha (barcha vaqt):\n{status_lines}\n\n"
        "Eslatma: har admin/lichka bo'yicha alohida taqsimot ko'p akkaunt "
        "qo'shilganda (MVP-5) qo'shiladi — hozircha bitta Teleton akkaunti ishlaydi."
    )


@admin_router.message(Command("audit"))
async def cmd_audit(message: Message) -> None:
    async with get_session() as session:
        entries = await list_recent(session, limit=20)

    if not entries:
        await message.answer("Hali hech qanday admin harakati qayd etilmagan.")
        return

    lines = [
        f"{e.created_at} — admin(tg_id={e.admin_tg_id}) — {e.action}: {e.details}" for e in entries
    ]
    await message.answer("So'nggi admin harakatlari:\n" + "\n".join(lines))


# --------------------------------------------------------------------------- #
# Shubhali holat: Xavfsiz / Bloklash — TZ 5.2, 9.3
# --------------------------------------------------------------------------- #
#
# Bu yerda faqat DB'dagi bayroqlar o'zgartiriladi. Haqiqiy dispatch (bot
# biriktirish, mijozga Telethon orqali xabar) Adminbot emas, Teleton
# jarayonidagi davriy tekshiruv (`teleton_service.relay._suspicious_resume_watcher`)
# tomonidan amalga oshiriladi — faqat u mijoz bilan "admin nomidan" gaplasha oladi.


@admin_router.callback_query(F.data.startswith("safe:"))
async def cb_mark_safe(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    case_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        if not await is_admin(session, callback.from_user.id):
            await callback.answer("Sizda ruxsat yo'q.", show_alert=True)
            return
        case = await session.get(Case, case_id)
        if case is None:
            await callback.answer("Case topilmadi.", show_alert=True)
            return
        user = await session.get(User, case.user_id)
        user.is_safe = True
        await log_action(session, callback.from_user.id, "mark_safe", f"case #{case_id}")
        await session.commit()

    await callback.message.edit_text((callback.message.text or "") + "\n\n✅ XAVFSIZ deb belgilandi.")
    await callback.answer("Xavfsiz deb belgilandi — Teleton tez orada dispatch qiladi.")


@admin_router.callback_query(F.data.startswith("block:"))
async def cb_block_user(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    case_id = int(callback.data.split(":", 1)[1])

    async with get_session() as session:
        if not await is_admin(session, callback.from_user.id):
            await callback.answer("Sizda ruxsat yo'q.", show_alert=True)
            return
        case = await session.get(Case, case_id)
        if case is None:
            await callback.answer("Case topilmadi.", show_alert=True)
            return
        user = await session.get(User, case.user_id)
        user.is_blocked = True
        case.status = CaseStatus.REJECTED
        await log_action(session, callback.from_user.id, "block_user", f"case #{case_id}")
        await session.commit()

    await callback.message.edit_text((callback.message.text or "") + "\n\n🚫 BLOKLANDI.")
    await callback.answer("Foydalanuvchi bloklandi.")


# --------------------------------------------------------------------------- #
# drop find <nomer> — TZ 9.2
# --------------------------------------------------------------------------- #


@admin_router.message(F.text.func(lambda t: t.lower().startswith("drop find")))
async def cmd_drop_find(message: Message) -> None:
    raw = message.text[len("drop find"):].strip()
    phone = extract_phone(raw) if raw else None
    if phone is None:
        await message.answer("Format: drop find <nomer> (masalan: drop find 998901234567)")
        return

    async with get_session() as session:
        result = await session.execute(
            select(Case).where(Case.phone == phone).order_by(Case.id.desc())
        )
        cases = result.scalars().all()

        if not cases:
            await message.answer(f"{phone} bo'yicha hech qanday murojaat topilmadi.")
            return

        blocks = []
        for case in cases:
            attempts_result = await session.execute(
                select(CouponAttempt)
                .where(CouponAttempt.case_id == case.id)
                .order_by(CouponAttempt.id)
            )
            attempts = attempts_result.scalars().all()
            attempts_text = (
                "\n".join(f"    - {a.coupon} -> {a.result.value} ({a.created_at})" for a in attempts)
                or "    (kupon urinishi yo'q)"
            )
            blocks.append(
                f"Case #{case.id} — {case.status.value}\n"
                f"  yaratildi: {case.created_at}, tasdiqlandi: {case.confirmed_at or '—'}\n"
                f"  bot_id: {case.bot_id or '—'}\n"
                f"  kupon urinishlari:\n{attempts_text}"
            )

    await message.answer(f"Nomer: {phone}\n\n" + "\n\n".join(blocks))


# --------------------------------------------------------------------------- #
# Ruxsatsiz foydalanuvchilar uchun fallback (TZ 12.2 — boshqa hech kim emas)
# --------------------------------------------------------------------------- #


@fallback_router.message()
async def cmd_denied(message: Message) -> None:
    await message.answer("Sizda ruxsat yo'q.")


async def main() -> None:
    bot = Bot(token=settings.adminbot_token)
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(fallback_router)

    await init_db()
    async with get_session() as session:
        await ensure_admins_seeded(session, settings.admin_tg_ids)
        await ensure_templates_seeded(session)

    log.info("Adminbot ishga tushdi.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
