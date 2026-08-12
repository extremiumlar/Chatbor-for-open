"""Rasm partiyasi oqimi — TZ v2 5-bo'lim (B-2).

Bu modul FAQAT qaror va DB qatlamı: partiya qayd etish, dublikat aniqlash,
caption qurish, taymerlarni ko'chirish. Telethon bilan haqiqiy forward
`teleton_service/manual_relay.py`da — shu ajratish tufayli butun mantiq
tarmoqsiz test qilinadi.
"""

import datetime
import json
import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select

from core.enums import CaseStatus, V2_OPEN_STATUSES
from core.logic.settings_store import get_check_delay_minutes, get_group_chat_id
from core.logic.templates import get_template
from core.models import (
    Admin,
    Case,
    JobKind,
    ScheduledJob,
    ScreenshotBatch,
    User,
)

log = logging.getLogger("screenshots")

# TZ v2 5.2 — caption va hisobotlarda Toshkent vaqti (UTC+5), utcnow emas.
TASHKENT_TZ = datetime.timezone(datetime.timedelta(hours=5))


def to_tashkent(dt: datetime.datetime) -> datetime.datetime:
    """Bazadagi naive-UTC vaqtni Toshkent vaqtiga o'giradi."""
    return dt.replace(tzinfo=datetime.timezone.utc).astimezone(TASHKENT_TZ)


def format_phone_pretty(canonical: str) -> str:
    """"998901234567" -> "+998 90 123 45 67" (caption uchun)."""
    if len(canonical) == 12 and canonical.startswith("998"):
        n = canonical[3:]
        return f"+998 {n[0:2]} {n[2:5]} {n[5:7]} {n[7:9]}"
    return canonical


@dataclass
class BatchDecision:
    """`register_batch` natijasi — relay shu asosda forward/alert qiladi."""

    # Nomer topilmadi (ochiq case yo'q) — relay partiyani kutish ro'yxatiga
    # oladi (§5.5: mijoz 30 daqiqada nomer yozsa, qayta urinadi).
    no_case: bool = False
    batch_id: int | None = None
    case_short_code: str | None = None
    # None bo'lsa guruh sozlanmagan — forward qilinmaydi (§5.5).
    group_chat_id: int | None = None
    caption: str | None = None
    # Mijoz lichkasiga tushadigan shablon matn (§5.3).
    customer_text: str | None = None
    is_duplicate: bool = False


class ScreenshotFlow:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        alert_sink: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        self.session_factory = session_factory
        self.alert_sink = alert_sink

    async def register_batch(
        self,
        admin_id: int,
        admin_name: str,
        tg_user_id: int,
        message_ids: list[int],
        image_count: int,
    ) -> BatchDecision:
        """Admin mijozga tashlagan rasm partiyasini qayd etadi.

        Qiladigan ishlari (TZ v2 5-bo'lim):
        1. Faol case shartini tekshiradi (§5.1) — yo'q bo'lsa `no_case`.
        2. Dublikat nomerni aniqlaydi (§5.4) — belgi + superadmin alert.
        3. `screenshot_batches` yozuvi yaratadi.
        4. Case -> SCREENSHOTS_SENT, rasmsizlik eslatmalarini yopadi,
           CHECK_DUE taymerini rasm vaqtidan qayta rejalaydi (§6.1 a).
        5. Guruh caption'i va mijoz matnini tayyorlaydi.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.tg_user_id == tg_user_id)
            )
            user = result.scalars().first()
            if user is None:
                return BatchDecision(no_case=True)

            case = await self._get_latest_open_case(session, user.id)
            if case is None:
                return BatchDecision(no_case=True)

            now = datetime.datetime.utcnow()

            # §5.4 — dublikat: shu nomer uchun AVVAL ham partiya tashlanganmi
            # (case'idan qat'i nazar — boshqa admin boshqa case ochgan
            # bo'lishi mumkin).
            prev = await self._find_previous_batch(session, case.phone)

            batch = ScreenshotBatch(
                case_id=case.id,
                admin_id=admin_id,
                phone=case.phone,
                image_count=image_count,
                file_ids=json.dumps(message_ids),
                is_duplicate=prev is not None,
                duplicate_of_batch_id=prev.id if prev is not None else None,
            )
            session.add(batch)

            # §6.1 a — holat va taymerlar. CHECK_QUEUED/CHECK_SENT'dan orqaga
            # qaytarilmaydi (tekshiruv allaqachon yo'lda bo'lsa, qo'shimcha
            # rasm uni to'xtatmasligi kerak).
            reschedule = case.status in (
                CaseStatus.NUMBER_RECEIVED,
                CaseStatus.SCREENSHOTS_SENT,
            )
            if reschedule:
                case.status = CaseStatus.SCREENSHOTS_SENT
                await self._close_jobs(
                    session, case.id, (JobKind.REMIND_NO_SCREENSHOT, JobKind.CHECK_DUE), now
                )
                delay_minutes = await get_check_delay_minutes(session)
                check_due_at = now + datetime.timedelta(minutes=delay_minutes)
                session.add(
                    ScheduledJob(kind=JobKind.CHECK_DUE, case_id=case.id, due_at=check_due_at)
                )
            else:
                check_due_at = await self._existing_check_due(session, case.id)

            await session.commit()
            await session.refresh(batch)

            group_chat_id = await get_group_chat_id(session)
            if group_chat_id is None:
                await self.alert_sink(
                    f"⚠️ Nazorat guruhi sozlanmagan — {case.short_code or case.id} "
                    f"rasmlari bazaga yozildi, lekin guruhga tushmadi. "
                    f"Adminbotdan guruhni belgilang.",
                    True,
                )

            caption = await self._build_caption(
                session, case, user, admin_name, now, check_due_at, prev
            )

            if prev is not None:
                await self.alert_sink(
                    f"⚠️ DUBLIKAT: {format_phone_pretty(case.phone)} uchun avval ham "
                    f"rasm tashlangan (partiya #{prev.id}, admin_id={prev.admin_id}). "
                    f"Yangi partiya: {case.short_code or case.id} (admin: {admin_name}). "
                    f"Ikki admin bitta mijoz ustida ishlayotgan bo'lishi mumkin.",
                    True,
                )

            customer_text = await get_template(session, "SCREENSHOT_FOLLOWUP")

            log.info(
                "Partiya #%s qayd etildi: case=%s, admin=%s, rasm=%s, dublikat=%s.",
                batch.id,
                case.short_code or case.id,
                admin_name,
                image_count,
                prev is not None,
            )
            return BatchDecision(
                batch_id=batch.id,
                case_short_code=case.short_code,
                group_chat_id=group_chat_id,
                caption=caption,
                customer_text=customer_text,
                is_duplicate=prev is not None,
            )

    async def record_group_post(
        self, batch_id: int, group_chat_id: int, group_message_id: int
    ) -> None:
        """Forward muvaffaqiyatli bo'lgach guruhdagi post manzilini saqlaydi
        (B-4'da reaksiya aynan shu xabarga qo'yiladi)."""
        async with self.session_factory() as session:
            batch = await session.get(ScreenshotBatch, batch_id)
            if batch is None:
                return
            batch.group_chat_id = group_chat_id
            batch.group_message_id = group_message_id
            await session.commit()

    # ------------------------------------------------------------------ #
    # Ichki yordamchilar
    # ------------------------------------------------------------------ #

    async def _get_latest_open_case(self, session, user_id: int) -> Case | None:
        result = await session.execute(
            select(Case).where(Case.user_id == user_id).order_by(Case.id.desc())
        )
        case = result.scalars().first()
        if case is None or case.status not in V2_OPEN_STATUSES:
            return None
        return case

    async def _find_previous_batch(self, session, phone: str) -> ScreenshotBatch | None:
        result = await session.execute(
            select(ScreenshotBatch)
            .where(ScreenshotBatch.phone == phone)
            .order_by(ScreenshotBatch.id.desc())
        )
        return result.scalars().first()

    async def _close_jobs(
        self, session, case_id: int, kinds: tuple[JobKind, ...], now: datetime.datetime
    ) -> None:
        result = await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.case_id == case_id,
                ScheduledJob.kind.in_(kinds),
                ScheduledJob.done_at.is_(None),
            )
        )
        for job in result.scalars().all():
            job.done_at = now

    async def _existing_check_due(self, session, case_id: int) -> datetime.datetime | None:
        result = await session.execute(
            select(ScheduledJob.due_at).where(
                ScheduledJob.case_id == case_id,
                ScheduledJob.kind == JobKind.CHECK_DUE,
                ScheduledJob.done_at.is_(None),
            )
        )
        row = result.first()
        return row[0] if row else None

    async def _build_caption(
        self,
        session,
        case: Case,
        user: User,
        admin_name: str,
        now: datetime.datetime,
        check_due_at: datetime.datetime | None,
        prev: ScreenshotBatch | None,
    ) -> str:
        """TZ v2 5.2 dagi tasdiqlangan format."""
        local_now = to_tashkent(now)
        customer = (
            f"@{user.tg_username} ({user.display_name})"
            if user.tg_username and user.display_name
            else f"@{user.tg_username}"
            if user.tg_username
            else user.display_name or f"id:{user.tg_user_id}"
        )
        lines = [
            f"📸 #{case.short_code or case.id}",
            f"👤 {customer}",
            f"📱 {format_phone_pretty(case.phone)}",
            f"🧑‍💼 Admin: {admin_name}",
            f"🕐 {local_now:%H:%M · %d.%m.%Y}",
        ]
        if check_due_at is not None:
            lines.append(f"⏳ Tekshiruv: {to_tashkent(check_due_at):%H:%M}")
        if prev is not None:
            prev_admin = await session.get(Admin, prev.admin_id)
            prev_case = await session.get(Case, prev.case_id)
            prev_code = (prev_case.short_code or prev_case.id) if prev_case else "?"
            lines.append(
                f"⚠️ Bu nomer uchun avval ham rasm tashlangan — #{prev_code} "
                f"(Admin: {prev_admin.name if prev_admin else '?'}, "
                f"{to_tashkent(prev.sent_at):%H:%M})"
            )
        return "\n".join(lines)
