"""Teleton — Telethon orqali admin lichkasini kuzatib, mijoz-bot oqimini
avtomatlashtiradi (TZ 1-2-bo'lim, MVP-1: haqiqiy Telethon + mock tekshiruv bot).
"""

import asyncio
import logging

from sqlalchemy import select
from telethon import TelegramClient, events

from core.config import settings
from core.db import get_session, init_db
from core.enums import CaseStatus
from core.logic.admins import ensure_admins_seeded
from core.logic.backup import daily_backup_loop
from core.logic.supervisor import spawn_supervised
from core.logic.bot_pool import ensure_bots_seeded
from core.logic.bot_patterns import missing_patterns
from core.logic.case_manager import CaseManager
from core.logic.coupon import extract_coupon
from core.logic.logging_setup import configure_logging
from core.logic.notifier import AdminNotifier
from core.logic.phone import extract_phone
from core.logic.reconciliation import reconcile_after_restart
from core.logic.settings_store import get_operator_codes
from core.logic.templates import ensure_templates_seeded
from core.models import Bot, Case, User
from teleton_service.mock_bot import MockVerificationBot
from teleton_service.real_bot_adapter import RealVerificationBotAdapter

# DIQQAT: `configure_logging` `main()` ichida — T-16 ga qarang (modul
# darajasida bo'lsa, testlar importda jonli log fayliga yozib yuborardi).
log = logging.getLogger("relay")

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

    try:
        # Audit J-3 — media tekshiruvi endi CAPTION bor-yo'qligidan qat'i
        # nazar birinchi bo'lib ishlaydi. Avval faqat `text` bo'sh bo'lganda
        # (captionsiz rasm) tekshirilardi — mijoz rasmga biror izoh
        # ("mana" va h.k.) qo'shsa, TZ 5.1 ogohlantirishi butunlay
        # ishlamay, xabar to'liq e'tiborsiz qoldirilardi.
        if event.photo or event.video or event.document:
            outcome = await case_manager.handle_non_text_coupon_input(
                tg_user_id, tg_username, display_name
            )
            if outcome is not None and outcome.customer_text:
                await event.reply(outcome.customer_text)
            return

        if not text:
            return

        # Audit J-9 (TZ 4.1) — operator kodlari ro'yxati endi Adminbot
        # orqali jonli sozlanadi (`.env` faqat boshlang'ich qiymat);
        # har xabarda joriy ro'yxat bazadan o'qiladi.
        async with get_session() as session:
            operator_codes = await get_operator_codes(session)
        phone = extract_phone(text, operator_codes)
        if phone is not None:
            outcome = await case_manager.handle_phone_detected(
                tg_user_id, tg_username, display_name, phone
            )
            if outcome.customer_text:
                await event.reply(outcome.customer_text)
            return

        # Audit J-2 — avval kupon faqat xabar AYNAN 6 ta raqamdan iborat
        # bo'lsagina tanilardi; nomer aniqlash kabi matn ICHIDAN qidirilmasdi
        # (TZ 1-bo'lim: mijoz "tabiiy suhbat" ichida yozadi). "kuponim
        # 123456" yoki bo'shliqli "123 456" kabi xabarlar butunlay
        # e'tiborsiz qoldirilardi.
        coupon = extract_coupon(text)
        if coupon is not None:
            outcome = await case_manager.handle_coupon_received(tg_user_id, coupon)
            if outcome is not None and outcome.customer_text:
                await event.reply(outcome.customer_text)
            return

        # Boshqa har qanday xabar — oddiy suhbat, tizim aralashmaydi.
    except Exception as exc:
        # Audit J-5 — avval bu yerda umuman try/except yo'q edi: kutilmagan
        # xato (masalan DB uzilishi) faqat Telethon'ning ichki logi orqali
        # ko'rinardi, adminga HECH QANDAY push bormasdi — TZ 12.1 (Q42)
        # "log HAM, kritik bo'lsa adminbotga push HAM" talabini buzardi.
        log.exception("Mijoz xabarini qayta ishlashda kutilmagan xato (tg_id=%s)", tg_user_id)
        await notifier.send(
            f"KRITIK: mijoz xabarini qayta ishlashda kutilmagan xato (tg_id={tg_user_id}): "
            f"{exc!r}",
            important=True,
        )


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
        except Exception as exc:
            # Audit J-5 — TZ 12.1 (Q42): log HAM, kritik bo'lsa adminbotga
            # push HAM. Avval faqat log yozilardi.
            log.exception("Shubhali case'larni qayta ishga tushirishda xato")
            await notifier.send(
                f"KRITIK: shubhali case'larni qayta ishga tushirishda xato: {exc!r}", important=True
            )


async def _admin_redispatch_watcher() -> None:
    """TZ 9.3 ("Qayta uzatish") — Adminbot qo'ygan bayroqni ko'rib dispatch qiladi.

    Adminbot Telethon'ga ega emas, shuning uchun o'zi botga yubora olmaydi va
    mijozga yoza olmaydi (TZ 13.1) — u faqat `admin_redispatch_requested`
    bayrog'ini qo'yadi, haqiqiy ishni shu yerda Teleton bajaradi.
    """
    while True:
        await asyncio.sleep(settings.suspicious_resume_poll_seconds)
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Case, User)
                    .join(User, Case.user_id == User.id)
                    .where(Case.admin_redispatch_requested.is_(True))
                )
                for case, user in result.all():
                    # Bayroq DISPATCHDAN OLDIN tozalanadi — aks holda dispatch
                    # paytida xato chiqsa, keyingi aylanishda cheksiz takrorlanardi.
                    case.admin_redispatch_requested = False
                    await session.commit()

                    outcome = await case_manager.redispatch_queued_case(session, case)
                    if outcome.customer_text:
                        await client.send_message(user.tg_user_id, outcome.customer_text)
                    log.info("Admin so'rovi bo'yicha case #%s qayta uzatildi.", case.id)
        except Exception as exc:
            # Audit J-5 — TZ 12.1 (Q42): log HAM, kritik bo'lsa adminbotga push HAM.
            log.exception("Admin so'ragan qayta uzatishda xato")
            await notifier.send(
                f"KRITIK: admin so'ragan qayta uzatishda xato: {exc!r}", important=True
            )


async def _force_release_watcher() -> None:
    """Audit J-4 (TZ 12) — Adminbot "Majburan bo'shatish" bosganda qo'yadigan
    `Bot.force_release_requested` bayrog'ini ko'rib, HAQIQIY (jarayon-ichidagi)
    `case_manager.pool.force_release`ni chaqiradi — shu orqali navbatda
    kutayotgan case (bo'lsa) darhol shu botga tayinlanadi, `admin_redispatch_requested`
    bilan bir xil naqsh (Adminbot Telethon'ga ega emas, faqat bayroq qo'yadi).
    """
    while True:
        await asyncio.sleep(settings.suspicious_resume_poll_seconds)
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Bot).where(Bot.force_release_requested.is_(True))
                )
                for bot in result.scalars().all():
                    bot.force_release_requested = False
                    await session.commit()
                    await case_manager.pool.force_release(session, bot.id)
                    log.info("Admin so'rovi bo'yicha bot #%s majburan bo'shatildi.", bot.id)
        except Exception as exc:
            log.exception("Majburan bo'shatishda xato")
            await notifier.send(f"KRITIK: bot majburan bo'shatishda xato: {exc!r}", important=True)


async def main() -> None:
    # T-16 — log sozlash faqat haqiqiy ishga tushishda (import paytida emas).
    configure_logging("teleton")

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

    # Fon sikllari kuzatuv ostida — `manual_relay`dagi bilan bir xil sabab
    # (`core.logic.supervisor` izohiga qarang): kuzatuvsiz sikl xato bilan
    # o'lsa, hech qayerda iz qolmaydi va nazoratchilar jimgina to'xtaydi.
    background_tasks = [
        spawn_supervised(
            "suspicious_resume_watcher", _suspicious_resume_watcher, notifier.send
        ),
        spawn_supervised(
            "admin_redispatch_watcher", _admin_redispatch_watcher, notifier.send
        ),
        spawn_supervised("force_release_watcher", _force_release_watcher, notifier.send),
        spawn_supervised(
            "daily_backup",
            lambda: daily_backup_loop(
                settings.database_url,
                settings.backup_dir,
                settings.backup_interval_seconds,
                settings.backup_retention,
                alert_sink=notifier.send,
            ),
            notifier.send,
        ),
    ]
    try:
        await client.run_until_disconnected()
    finally:
        for task in background_tasks:
            task.cancel()
        await notifier.close()  # Audit N-3


if __name__ == "__main__":
    asyncio.run(main())
