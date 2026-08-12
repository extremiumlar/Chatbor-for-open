"""Teleton v2 — qo'lda admin oqimi kirish nuqtasi (TZ v2, B-1 skelet).

v1 `teleton_service/relay.py`dan farqi (TZ v2 1.1):
- BITTA emas, N ta Telethon klienti (har faol admin uchun bitta) —
  `MultiClientManager` boshqaradi.
- Kiruvchi BILAN BIRGA CHIQUVCHI xabarlar ham kuzatiladi (admin o'zi
  yozgan rasm/buyruqlar — TZ v2 5/6-bo'lim).
- Tekshiruv bot pool YO'Q — `ManualCaseManager` faqat qayd yuritadi;
  tekshiruvchi lichka bilan ishlash B-3'da qo'shiladi.

Eski relay.py'ga TEGILMAGAN (TZ v2 12-bo'lim: "kod qoladi, ulanmaydi") —
ishga tushirish endi:  python -m teleton_service.manual_relay
"""

import asyncio
import datetime
import logging
import random

from telethon import TelegramClient, events
from telethon.tl import functions, types

from core.config import settings
from core.db import get_session, init_db
from core.logic.admins import ensure_admins_seeded, list_admins
from core.logic.backup import daily_backup_loop
from core.logic.coupon import extract_coupon
from core.logic.logging_setup import configure_logging
from core.logic.manual_case import ManualCaseManager
from core.logic.notifier import AdminNotifier
from core.logic.phone import extract_phone
from core.logic.check_engine import CheckEngine
from core.logic.job_poller import JobPoller
from core.logic.result_flow import REACTION_BY_OUTCOME, ResultDistributor
from core.logic.screenshots import ScreenshotFlow, to_tashkent
from core.logic.v2_stats import (
    ensure_daily_report_scheduled,
    gather_v2_stats,
    render_daily_group_report,
    render_daily_superadmin_report,
    tashkent_day_start_utc,
)
from core.logic.settings_store import (
    get_checker_account,
    get_daily_report_time,
    get_drip_interval_seconds,
    get_group_chat_id,
    get_image_batch_window_seconds,
    get_operator_codes,
)
from core.logic.templates import ensure_templates_seeded
from core.models import (
    Admin,
    BatchOutcome,
    Case,
    CheckTrigger,
    OutcomeSource,
    ScreenshotBatch,
    User,
)
from sqlalchemy import select
from teleton_service.batch_collector import BatchCollector
from teleton_service.multi_client import MultiClientManager

configure_logging("teleton_v2")
log = logging.getLogger("manual_relay")

notifier = AdminNotifier(session_factory=get_session, bot_token=settings.adminbot_token)

case_manager = ManualCaseManager(
    session_factory=get_session,
    alert_sink=notifier.send,
    suspicious_alert_sink=notifier.send_suspicious_alert,
)

screenshot_flow = ScreenshotFlow(session_factory=get_session, alert_sink=notifier.send)

multi = MultiClientManager(
    session_factory=get_session,
    api_id=settings.api_id,
    api_hash=settings.api_hash,
    sessions_dir=settings.sessions_dir,
    alert_sink=notifier.send,
)

# §5.5 — nomersiz kelgan rasm partiyalari: mijoz 30 daqiqa ichida nomer yozsa
# avtomatik bog'lanadi. Xotirada (restart'da yo'qoladi — bu qabul qilingan
# chekka holat: rasm baribir mijoz lichkasida turadi, admin qayta tashlashi
# yoki /check qilishi mumkin). Kalit: (admin_id, chat_id).
_PENDING_TTL = datetime.timedelta(minutes=30)
_pending_batches: dict[tuple[int, int], tuple[list, datetime.datetime]] = {}

# main() ishga tushishida bazadan bir marta o'qiladi (adminbot orqali
# o'zgartirilgan qiymat qayta ishga tushirishda kuchga kiradi).
_batch_window_seconds: float = settings.image_batch_window_seconds


async def _send_to_checker(admin_id: int, text: str) -> int | None:
    """CheckEngine uchun: so'rovni O'SHA ADMINNING akkauntidan tekshiruvchi
    lichkaga yuboradi (TZ v2 6.3). Muvaffaqiyatsiz bo'lsa None — so'rov
    navbatda qoladi."""
    managed = multi.clients.get(admin_id)
    if managed is None or not managed.client.is_connected():
        return None
    async with get_session() as session:
        checker = await get_checker_account(session)
    if checker is None:
        return None
    try:
        entity = int(checker) if checker.lstrip("-").isdigit() else checker
        msg = await managed.client.send_message(entity, text)
        return msg.id
    except Exception:
        log.exception(
            "Tekshiruvchiga yuborish xatosi (admin_id=%s, checker=%s)",
            admin_id,
            checker,
        )
        return None


# Telegram standart reaksiya to'plamida ⚠️ va ⏳ YO'Q — rad etilsa shu
# muqobillar bilan qayta uriniladi (ma'nosi yaqin, to'plamda mavjud).
_REACTION_FALLBACK = {"⚠️": "🤔", "⏳": "😴"}


async def _set_reaction(
    admin_id: int, chat_id: int, message_id: int, emoji: str
) -> bool:
    """ResultDistributor uchun: guruh postiga reaksiya (TZ v2 7.3) — postni
    guruhga tashlagan adminning akkauntidan."""
    managed = multi.clients.get(admin_id)
    if managed is None or not managed.client.is_connected():
        return False
    for attempt_emoji in (emoji, _REACTION_FALLBACK.get(emoji)):
        if attempt_emoji is None:
            break
        try:
            await managed.client(
                functions.messages.SendReactionRequest(
                    peer=chat_id,
                    msg_id=message_id,
                    reaction=[types.ReactionEmoji(emoticon=attempt_emoji)],
                )
            )
            return True
        except Exception:
            log.warning(
                "Reaksiya qo'yilmadi (chat=%s, msg=%s, emoji=%s)",
                chat_id,
                message_id,
                attempt_emoji,
            )
    return False


async def _send_customer(admin_id: int, customer_tg_id: int, text: str) -> bool:
    """ResultDistributor uchun: natijani mijozga O'SHA ADMIN akkauntidan
    yozish (TZ v2 7.2)."""
    managed = multi.clients.get(admin_id)
    if managed is None or not managed.client.is_connected():
        return False
    try:
        # TZ v2 4.5 — tabiiy pauza.
        await asyncio.sleep(random.uniform(1.0, 3.0))
        await managed.client.send_message(customer_tg_id, text)
        return True
    except Exception:
        log.exception(
            "Mijozga natija yuborilmadi (admin_id=%s, tg_id=%s)",
            admin_id,
            customer_tg_id,
        )
        return False


distributor = ResultDistributor(
    session_factory=get_session,
    alert_sink=notifier.send,
    set_reaction=_set_reaction,
    send_customer=_send_customer,
    failed_confirmation=notifier.send_failed_confirmation,
)

check_engine = CheckEngine(
    session_factory=get_session,
    alert_sink=notifier.send,
    send_to_checker=_send_to_checker,
    result_hook=distributor.on_result,
    stalled_hook=distributor.on_stalled,
)

async def _daily_report() -> None:
    """TZ v2 8.1/8.3 — kunlik hisobot: guruhga xulosa (21:00 Toshkent),
    superadmin (OWNER/ROP) lichkalariga batafsilroq nusxa."""
    now = datetime.datetime.utcnow()
    async with get_session() as session:
        report = await gather_v2_stats(session, tashkent_day_start_utc(now))
        group_id = await get_group_chat_id(session)
        admins = await list_admins(session)

    date_str = to_tashkent(now).strftime("%d.%m.%Y")
    if group_id is not None:
        await notifier.send_to_chat(group_id, render_daily_group_report(report, date_str))
    detailed = render_daily_superadmin_report(report, date_str)
    for a in admins:
        if a.role.value in ("OWNER", "ROP"):
            await notifier.send_to_chat(a.tg_user_id, detailed)


job_poller = JobPoller(
    session_factory=get_session,
    engine=check_engine,
    alert_sink=notifier.send,
    distributor=distributor,
    daily_report=_daily_report,
)


async def _is_checker(sender_id: int, sender_username: str | None) -> bool:
    """Kiruvchi xabar tekshiruvchi lichkadanmi — MUHIM: bu tekshiruv nomer
    aniqlashdan OLDIN turadi (tekshiruvchi javobida nomer bo'ladi, uni mijoz
    deb qabul qilib bo'lmaydi)."""
    async with get_session() as session:
        checker = await get_checker_account(session)
    if checker is None:
        return False
    if checker.lstrip("-").isdigit():
        return sender_id == int(checker)
    return (sender_username or "").lower() == checker.lower()


async def _find_case_for_check(chat_id: int, phone: str) -> Case | None:
    """/check uchun case topish: avval shu mijozning (chat) shu nomerli
    eng so'nggi case'i; topilmasa nomer bo'yicha eng so'nggisi."""
    async with get_session() as session:
        result = await session.execute(
            select(Case)
            .join(User, Case.user_id == User.id)
            .where(User.tg_user_id == chat_id, Case.phone == phone)
            .order_by(Case.id.desc())
        )
        case = result.scalars().first()
        if case is not None:
            return case
        result = await session.execute(
            select(Case).where(Case.phone == phone).order_by(Case.id.desc())
        )
        return result.scalars().first()


async def _drip_loop() -> None:
    """TZ v2 6.2 — global tomchilagich: har intervalda ko'pi bilan bitta
    so'rov tekshiruvchiga chiqadi."""
    while True:
        try:
            async with get_session() as session:
                interval = await get_drip_interval_seconds(session)
        except Exception:
            interval = 20.0
        await asyncio.sleep(interval)
        try:
            await check_engine.drip_tick()
        except Exception as exc:
            log.exception("Drip tick xatosi")
            await notifier.send(f"KRITIK: drip navbat xatosi: {exc!r}", important=True)


def wire_handlers(client: TelegramClient, admin: Admin) -> None:
    """Bitta admin klientiga hodisa ishlovchilarini o'rnatadi.

    `admin` closure orqali bog'lanadi — shu klientdagi HAR hodisa aynan shu
    adminga tegishli (TZ v2 4.2: "qaysi admin" savoli avtomatik hal).
    """

    async def process_batch(chat_id: int, messages: list) -> None:
        """Partiya tayyor — qayd etish, guruhga forward, mijozga matn (§5.2/5.3)."""
        decision = await screenshot_flow.register_batch(
            admin.id, admin.name, chat_id, [m.id for m in messages], len(messages)
        )

        if decision.no_case:
            # §5.5 — nomer hali yo'q: guruhga tushmaydi, kutish ro'yxatiga.
            _pending_batches[(admin.id, chat_id)] = (
                messages,
                datetime.datetime.utcnow(),
            )
            await notifier.send(
                f"⚠️ {admin.name} rasm tashladi, lekin mijozdan (chat_id={chat_id}) "
                f"nomer topilmadi — rasm guruhga tushmadi. Mijoz 30 daqiqada nomer "
                f"yozsa avtomatik bog'lanadi.",
                important=True,
            )
            return

        if decision.group_chat_id is not None:
            try:
                # TZ v2 4.5 — shaxsiy akkauntdan avtomatik amallar orasida
                # tabiiy pauza (flood/spam-belgi xavfini kamaytiradi).
                await asyncio.sleep(random.uniform(1.0, 3.0))
                await client.forward_messages(decision.group_chat_id, messages)
                caption_msg = await client.send_message(
                    decision.group_chat_id, decision.caption
                )
                await screenshot_flow.record_group_post(
                    decision.batch_id, decision.group_chat_id, caption_msg.id
                )
            except Exception as exc:
                log.exception(
                    "Guruhga forward xatosi (admin=%s, batch=%s)",
                    admin.name,
                    decision.batch_id,
                )
                await notifier.send(
                    f"KRITIK: {decision.case_short_code} rasmlarini guruhga "
                    f"yuborib bo'lmadi (admin: {admin.name}): {exc!r}. "
                    f"Partiya bazada saqlangan.",
                    important=True,
                )

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

    collector = BatchCollector(process_batch, window_seconds=_batch_window_seconds)

    async def flush_pending_batch(chat_id: int) -> None:
        """Nomer keyin kelganda (§5.5) — kutib turgan partiyani bog'laydi."""
        pending = _pending_batches.pop((admin.id, chat_id), None)
        if pending is None:
            return
        messages, stored_at = pending
        if datetime.datetime.utcnow() - stored_at > _PENDING_TTL:
            return  # 30 daqiqadan eski — e'tiborsiz
        await process_batch(chat_id, messages)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_incoming(event: events.NewMessage.Event) -> None:
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return

        tg_user_id = event.sender_id
        tg_username = getattr(sender, "username", None)
        display_name = " ".join(
            part
            for part in [
                getattr(sender, "first_name", None),
                getattr(sender, "last_name", None),
            ]
            if part
        ) or None

        text = (event.raw_text or "").strip()
        if not text:
            return  # v2'da mijoz rasmiga tizim javob bermaydi (kupon oqimi yo'q)

        try:
            # MUHIM: tekshiruvchi marshruti NOMER aniqlashdan OLDIN —
            # tekshiruvchi javobida nomer bo'ladi ("...4567 bor"), uni mijoz
            # nomeri deb qabul qilish halokatli xato bo'lardi.
            if await _is_checker(tg_user_id, tg_username):
                await check_engine.handle_checker_reply(
                    admin.id, text, reply_to_msg_id=event.message.reply_to_msg_id
                )
                return

            async with get_session() as session:
                operator_codes = await get_operator_codes(session)

            phone = extract_phone(text, operator_codes)
            if phone is not None:
                outcome = await case_manager.handle_phone_detected(
                    admin.id, tg_user_id, tg_username, display_name, phone
                )
                if outcome.customer_text:
                    # Faqat ALREADY_CONFIRMED holati — boshqa hamma narsada
                    # tizim jim, admin tabiiy suhbatda o'zi yozadi.
                    await event.reply(outcome.customer_text)
                # §5.5 — admin rasmni nomerdan OLDIN tashlagan bo'lsa,
                # endi case ochildi — kutayotgan partiyani bog'laymiz.
                await flush_pending_batch(event.chat_id)
                return

            coupon = extract_coupon(text)
            if coupon is not None:
                # TZ v2 9.2 — kupon faqat signal/dalil sifatida saqlanadi.
                await case_manager.handle_coupon_detected(tg_user_id, coupon)
                return

            # Boshqa har qanday xabar — oddiy suhbat, tizim aralashmaydi.
        except Exception as exc:
            log.exception(
                "Kiruvchi xabarni qayta ishlashda xato (admin=%s, tg_id=%s)",
                admin.name,
                tg_user_id,
            )
            await notifier.send(
                f"KRITIK: kiruvchi xabarni qayta ishlashda xato "
                f"(admin={admin.name}, tg_id={tg_user_id}): {exc!r}",
                important=True,
            )

    @client.on(events.Raw(types.UpdateMessageReactions))
    async def on_reaction_update(update) -> None:
        """TZ v2 7.3 — guruhdagi reaksiya QO'LDA o'zgartirilsa, tizim buni
        o'qib bazaga yozadi (outcome_source=MANUAL, override sifatida
        statistikada alohida ko'rinadi). Best-effort: faqat 👍/👎 override
        sifatida qabul qilinadi."""
        try:
            from telethon import utils as tl_utils

            chat_id = tl_utils.get_peer_id(update.peer)
            emojis = [
                r.reaction.emoticon
                for r in (update.reactions.results or [])
                if isinstance(r.reaction, types.ReactionEmoji)
            ]

            async with get_session() as session:
                result = await session.execute(
                    select(ScreenshotBatch).where(
                        ScreenshotBatch.group_chat_id == chat_id,
                        ScreenshotBatch.group_message_id == update.msg_id,
                    )
                )
                batch = result.scalars().first()
                if batch is None:
                    return

                expected = REACTION_BY_OUTCOME.get(batch.outcome)
                # Tizimning o'z avtomatik reaksiyasi ham shu hodisani beradi —
                # kutilgan emoji bilan mos bo'lsa e'tiborsiz.
                manual_map = {"👍": BatchOutcome.PASSED, "👎": BatchOutcome.FAILED}
                new_outcome = None
                for e in emojis:
                    if e in manual_map and e != expected:
                        new_outcome = manual_map[e]
                        break
                if new_outcome is None or new_outcome == batch.outcome:
                    return

                batch.outcome = new_outcome
                batch.outcome_source = OutcomeSource.MANUAL
                batch.reacted_at = datetime.datetime.utcnow()
                recent = getattr(update.reactions, "recent_reactions", None) or []
                if recent:
                    batch.reacted_by = getattr(recent[0].peer_id, "user_id", None)
                await session.commit()
                batch_id = batch.id

            await notifier.send(
                f"✍️ Guruhda reaksiya QO'LDA o'zgartirildi: partiya #{batch_id} "
                f"→ {new_outcome.value} (override — statistikada alohida).",
                important=True,
            )
        except Exception:
            log.exception("Reaksiya o'zgarishini o'qishda xato (admin=%s)", admin.name)

    @client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private))
    async def on_outgoing(event: events.NewMessage.Event) -> None:
        """Admin O'ZI yozgan xabarlar — TZ v2 ning yuragi.

        - rasm -> partiya yig'ish + guruhga forward (B-2, shu yerda)
        - /check -> tekshiruvni darhol boshlash (B-3, hali skelet)
        """
        try:
            if event.photo:
                # §5.1 — partiyaga yig'ish: albom (grouped_id) yoki N-soniyalik
                # oyna. Faol case sharti ScreenshotFlow ichida tekshiriladi.
                collector.add(
                    event.chat_id, event.message, grouped_id=event.grouped_id
                )
                return

            text = (event.raw_text or "").strip()
            if text.lower().startswith("/check"):
                await handle_check_command(event, text)
        except Exception:
            log.exception("Chiquvchi xabar kuzatuvida xato (admin=%s)", admin.name)

    async def handle_check_command(event: events.NewMessage.Event, text: str) -> None:
        """TZ v2 6.1 b — admin nomerli xabarga reply qilib /check yozadi.

        Qadamlar: (1) /check xabari DARHOL o'chiriladi — mijoz komandani
        ko'rmasligi kerak; (2) nomer argumentdan yoki reply'dan olinadi;
        (3) so'rov navbatga qo'yiladi (rejalashtirilgan avtomatik tekshiruv
        engine ichida bekor qilinadi); (4) adminga adminbot orqali javob.
        """
        # (1) — komandani o'chirish (ikkala tomondan, revoke=True).
        try:
            await event.message.delete(revoke=True)
        except Exception:
            log.exception("/check xabarini o'chirib bo'lmadi (admin=%s)", admin.name)

        async with get_session() as session:
            operator_codes = await get_operator_codes(session)

        # (2) — nomer: avval argumentdan (/check +99890...), keyin reply'dan.
        phone = None
        arg = text[len("/check"):].strip()
        if arg:
            phone = extract_phone(arg, operator_codes)
        if phone is None:
            try:
                replied = await event.message.get_reply_message()
            except Exception:
                replied = None
            if replied is not None:
                phone = extract_phone(replied.raw_text or "", operator_codes)

        if phone is None:
            await notifier.send(
                f"⚠️ {admin.name}: /check — nomer topilmadi. Nomerli xabarga "
                f"reply qiling yoki /check +99890xxxxxxx ko'rinishida yozing.",
                important=True,
            )
            return

        case = await _find_case_for_check(event.chat_id, phone)
        if case is None:
            await notifier.send(
                f"⚠️ {admin.name}: /check {phone} — bu nomer bo'yicha case "
                f"topilmadi (mijoz nomerni hali yozmaganmi?).",
                important=True,
            )
            return

        status_text = await check_engine.request_check(
            case.id, CheckTrigger.MANUAL, admin.id
        )
        await notifier.send(
            f"🔎 {admin.name}: /check {phone} ({case.short_code or case.id}) — "
            f"{status_text}",
            important=True,
        )


async def main() -> None:
    global _batch_window_seconds

    await init_db()
    async with get_session() as session:
        await ensure_admins_seeded(session, settings.admin_tg_ids)
        await ensure_templates_seeded(session)
        # Partiya oynasi bazadan (adminbot orqali sozlanadi); o'zgarish
        # keyingi qayta ishga tushirishda kuchga kiradi.
        _batch_window_seconds = await get_image_batch_window_seconds(session)
        # B-5 — kunlik hisobot zanjiri kafolatlanadi (idempotent).
        await ensure_daily_report_scheduled(
            session, await get_daily_report_time(session)
        )

    connected = await multi.start_all(wire_handlers)
    log.info("Teleton v2 ishga tushdi: %s ta admin sessiyasi ulandi.", connected)
    if connected:
        await notifier.send(
            f"🟢 Teleton v2 ishga tushdi — {connected} ta admin sessiyasi ulandi.",
            important=False,
        )

    background_tasks = [
        asyncio.create_task(multi.health_loop()),
        # B-3 — taymerlar bazadan (restart'dan omon), drip navbat.
        asyncio.create_task(job_poller.run_loop()),
        asyncio.create_task(_drip_loop()),
        asyncio.create_task(
            daily_backup_loop(
                settings.database_url,
                settings.backup_dir,
                settings.backup_interval_seconds,
                settings.backup_retention,
                alert_sink=notifier.send,
            )
        ),
    ]
    try:
        # Klientlar fon rejimida ishlaydi (Telethon o'z receive-loop'ini
        # yuritadi); jarayon to'xtatilguncha (Ctrl+C / systemd stop) kutamiz.
        await asyncio.Event().wait()
    finally:
        for task in background_tasks:
            task.cancel()
        await multi.stop_all()
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
