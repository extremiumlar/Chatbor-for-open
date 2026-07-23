"""Teleton — Telethon orqali admin lichkasini kuzatib, mijoz-bot oqimini
avtomatlashtiradi (TZ 1-2-bo'lim, MVP-1: haqiqiy Telethon + mock tekshiruv bot).
"""

import asyncio
import logging
import re

from sqlalchemy import select
from telethon import TelegramClient, events

from core.config import settings
from core.db import get_session, init_db
from core.enums import CaseStatus
from core.logic.admins import ensure_admins_seeded
from core.logic.backup import daily_backup_loop
from core.logic.bot_pool import ensure_bots_seeded
from core.logic.bot_patterns import missing_patterns
from core.logic.case_manager import CaseManager
from core.logic.logging_setup import configure_logging
from core.logic.notifier import AdminNotifier
from core.logic.phone import extract_phone
from core.logic.reconciliation import reconcile_after_restart
from core.logic.templates import ensure_templates_seeded
from core.models import Case, User
from teleton_service.mock_bot import MockVerificationBot
from teleton_service.real_bot_adapter import RealVerificationBotAdapter

configure_logging("teleton")
log = logging.getLogger("relay")

_COUPON_RE = re.compile(r"^\d{6}$")

client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
notifier = AdminNotifier(session_factory=get_session, bot_token=settings.adminbot_token)


async def _notify_customer(tg_user_id: int, text: str) -> None:
    await client.send_message(tg_user_id, text)


case_manager = CaseManager(
    session_factory=get_session,
    bot_client=MockVerificationBot(),
    alert_sink=notifier.send,
    notify_customer=_notify_customer,
    suspicious_alert_sink=notifier.send_suspicious_alert,
    image_warning_sink=notifier.send_image_warning,
)


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_private_message(event: events.NewMessage.Event) -> None:
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or event.out:
        return

    tg_user_id = event.sender_id
    tg_username = getattr(sender, "username", None)
    display_name = " ".join(
        part for part in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if part
    ) or None

    text = (event.raw_text or "").strip()

    if not text:
        if event.photo or event.video or event.document:
            # TZ 5.1 — kupon o'rniga rasm/media kelsa.
            outcome = await case_manager.handle_non_text_coupon_input(
                tg_user_id, tg_username, display_name
            )
            if outcome is not None and outcome.customer_text:
                await event.reply(outcome.customer_text)
        return

    phone = extract_phone(text)
    if phone is not None:
        outcome = await case_manager.handle_phone_detected(tg_user_id, tg_username, display_name, phone)
        if outcome.customer_text:
            await event.reply(outcome.customer_text)
        return

    if _COUPON_RE.match(text):
        outcome = await case_manager.handle_coupon_received(tg_user_id, text)
        if outcome is not None and outcome.customer_text:
            await event.reply(outcome.customer_text)
        return

    # Boshqa har qanday xabar — oddiy suhbat, tizim aralashmaydi.


# --------------------------------------------------------------------------- #
# Shubhali holat "Xavfsiz" deb belgilangach case'ni dispatch qilish (TZ 5.2)
# --------------------------------------------------------------------------- #
#
# Adminbot (alohida jarayon) faqat DB'da user.is_safe=True qiladi — haqiqiy
# dispatch (bot biriktirish, mijozga Telethon orqali xabar) faqat shu yerda,
# Teleton jarayonida bo'lishi mumkin (faqat u mijoz bilan "admin nomidan"
# gaplasha oladi). Shuning uchun davriy tekshiruv (poll) kerak — TZ 13.1.


async def _suspicious_resume_watcher() -> None:
    while True:
        await asyncio.sleep(settings.suspicious_resume_poll_seconds)
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Case, User)
                    .join(User, Case.user_id == User.id)
                    .where(Case.status == CaseStatus.SUSPICIOUS_HOLD, User.is_safe.is_(True))
                )
                for case, user in result.all():
                    outcome = await case_manager.resume_suspicious_case(session, case)
                    if outcome.customer_text:
                        await client.send_message(user.tg_user_id, outcome.customer_text)
        except Exception:
            log.exception("Shubhali case'larni qayta ishga tushirishda xato")


async def main() -> None:
    await init_db()
    async with get_session() as session:
        await ensure_bots_seeded(session, settings.bot_pool_usernames)
        await ensure_admins_seeded(session, settings.admin_tg_ids)
        await ensure_templates_seeded(session)

    if settings.use_real_verification_bots:
        # TZ 9.4 (Q16) — bot-tanish shablonlari to'liq kiritilmaguncha
        # real bot rejimi ishga tushmaydi (tizim STOP + sabab).
        async with get_session() as session:
            missing = await missing_patterns(session)
        if missing:
            reason = (
                "Bot 'tanish' shablonlari to'liq kiritilmagan "
                f"({', '.join(missing)}) — tizim to'xtatildi (TZ 9.4, Q16). "
                "Adminbot orqali /setbotpattern bilan to'ldiring."
            )
            log.critical(reason)
            await notifier.send(reason, important=True)
            return

        case_manager.bot_client = RealVerificationBotAdapter(client)
        log.warning(
            "Real tekshiruv bot rejimi YOQILDI — bu adapter hali haqiqiy botga "
            "qarshi sinalmagan, ehtiyotkorlik bilan kuzating."
        )

    await client.start()
    me = await client.get_me()
    log.info("Teleton ishga tushdi: %s (id=%s)", me.first_name, me.id)

    # TZ 12-bo'lim (Q37) — qayta ishga tushganda yarim qolgan case'larni ko'rib chiqish.
    await reconcile_after_restart(case_manager, get_session, notifier.send, _notify_customer)

    watcher_task = asyncio.create_task(_suspicious_resume_watcher())
    backup_task = asyncio.create_task(
        daily_backup_loop(
            settings.database_url,
            settings.backup_dir,
            settings.backup_interval_seconds,
            settings.backup_retention,
        )
    )
    try:
        await client.run_until_disconnected()
    finally:
        watcher_task.cancel()
        backup_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
