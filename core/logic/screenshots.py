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
from html import escape
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
    case_id: int | None = None
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
        media_ids: list[int] | None = None,
        reply_to_msg_id: int | None = None,
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

            case = await self._resolve_case(
                session, user, reply_to_msg_id, admin_name
            )
            if case is None:
                return BatchDecision(no_case=True)

            now = datetime.datetime.utcnow()

            # §5.4 — dublikat ikki mezon bo'yicha aniqlanadi:
            #   (1) NOMER — shu nomer uchun BOSHQA case'da partiya bo'lganmi;
            #   (2) RASM  — aynan shu rasm(lar) avval ham tashlanganmi.
            # Ikkinchisi kerak, chunki bir mijoz nomerni o'zgartirib o'sha
            # skrinshotni qayta tashlashi mumkin — nomer bo'yicha tekshiruv
            # buni o'tkazib yuborardi. Aynan SHU case'ga qo'shimcha rasm
            # tashlash dublikat emas (§6.1a — normal holat).
            media_ids = media_ids or []
            prev = await self._find_previous_batch(
                session, case.phone, case.id, media_ids
            )

            batch = ScreenshotBatch(
                case_id=case.id,
                admin_id=admin_id,
                phone=case.phone,
                image_count=image_count,
                file_ids=json.dumps(message_ids),
                media_ids=json.dumps(media_ids),
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
                # Sabab ikki xil bo'lishi mumkin va ular teng emas: bittasi —
                # ikki adminning to'qnashuvi (darhol hal qilinishi kerak),
                # ikkinchisi — o'sha adminning bir nomerni ikki marta
                # kiritgani. Avval ikkovi ham "ikki admin ishlayapti" deb
                # xabar qilinardi.
                prev_admin = await session.get(Admin, prev.admin_id)
                prev_nomi = prev_admin.name if prev_admin else f"admin_id={prev.admin_id}"
                prev_case = await session.get(Case, prev.case_id)
                prev_code = (prev_case.short_code or prev_case.id) if prev_case else "?"
                if prev.admin_id == admin_id:
                    sabab = (
                        f"O'SHA admin ({admin_name}) bu nomer uchun boshqa "
                        f"case'da ({prev_code}) ham rasm tashlagan — ikki marta "
                        f"kiritilgan bo'lishi mumkin."
                    )
                else:
                    sabab = (
                        f"IKKI ADMIN bitta mijoz ustida ishlayapti: "
                        f"{prev_nomi} ({prev_code}) va {admin_name}."
                    )
                await self.alert_sink(
                    f"⚠️ DUBLIKAT: {format_phone_pretty(case.phone)} — "
                    f"avvalgi partiya #{prev.id}, yangi partiya "
                    f"{case.short_code or case.id}. {sabab}",
                    True,
                )

            # §5.3 matni case boshiga BIR MARTA yuboriladi. Admin rasmni
            # qayta tashlashi normal holat (§6.1a), lekin mijoz uchun bir xil
            # matnni qayta-qayta olish spam bo'ladi — jonli sinovda 3 partiya
            # ketma-ket tashlanganda mijoz "tekshirish jarayonida..." matnini
            # 3 marta oldi.
            #
            # MUHIM: shart "birinchi partiyami?" EMAS, "matn YUBORILGANMI?".
            # Avvalgi variant partiya borligiga qarardi va jonli sinovda
            # teshik chiqdi: birinchi partiya soya rejimida tashlangan
            # (matn to'silgan), keyingilari esa "birinchi emas" deb jim
            # qolgan — mijoz matnni hech qachon olmagan. Yuborilgani
            # `mark_followup_sent` bilan belgilanadi (haqiqiy yuborishdan
            # KEYIN), shuning uchun to'silgan yoki xato bergan yuborish
            # keyingi partiyada qayta uriniladi.
            customer_text = (
                None
                if case.followup_sent_at is not None
                else await get_template(session, "SCREENSHOT_FOLLOWUP")
            )

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
                case_id=case.id,
                case_short_code=case.short_code,
                group_chat_id=group_chat_id,
                caption=caption,
                customer_text=customer_text,
                is_duplicate=prev is not None,
            )

    async def mark_followup_sent(self, case_id: int) -> None:
        """§5.3 matni mijozga HAQIQATAN yetkazilgach chaqiriladi.

        Aynan yuborishdan KEYIN belgilanadi: soya rejimida to'silgan yoki
        tarmoq xatosi bilan ketmagan matn belgilanmaydi va keyingi partiyada
        qayta uriniladi. Aks holda mijoz matnni umuman olmay qolardi.
        """
        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None or case.followup_sent_at is not None:
                return
            case.followup_sent_at = datetime.datetime.utcnow()
            await session.commit()

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

    async def _resolve_case(
        self, session, user: User, reply_to_msg_id: int | None, admin_name: str
    ) -> Case | None:
        """Partiya QAYSI nomerga tegishli ekanini aniqlaydi.

        Rasmning o'zida nomer haqida ma'lumot yo'q, shuning uchun mijozda
        bir nechta ochiq nomer bo'lsa tizim taxmin qila olmaydi. Tartib:

        1. Admin mijozning NOMERLI XABARIGA reply qilgan bo'lsa — aynan
           o'sha case (`Case.origin_message_id`). Bu yagona ANIQ usul.
        2. Ochiq case bitta bo'lsa — noaniqlik yo'q, o'sha.
        3. Bir nechta ochiq case bor va reply yo'q — tizim TAXMIN
           QILMAYDI: adminga darhol ogohlantirish ketadi va partiya rasm
           kutayotgan ENG ESKI case'ga yoziladi (admin odatda nomerlarni
           kelgan tartibda ovoz beradi).

        Avval har doim "oxirgi ochiq case" olinardi — natijada ikkinchi
        nomer uchun tashlangan rasm BIRINCHI nomer bilan guruhga tushardi.
        """
        ochiq = (
            await session.execute(
                select(Case)
                .where(Case.user_id == user.id, Case.status.in_(V2_OPEN_STATUSES))
                .order_by(Case.id)
            )
        ).scalars().all()
        if not ochiq:
            return None

        # 1) Reply — aniq ko'rsatma.
        if reply_to_msg_id is not None:
            for case in ochiq:
                if case.origin_message_id == reply_to_msg_id:
                    return case
            # Reply bor, lekin nomerli xabarga emas (masalan eski rasmga).
            # Bu ham noaniqlik — pastdagi shoxga tushadi.

        if len(ochiq) == 1:
            return ochiq[0]

        # 3) Noaniq — ogohlantiramiz va taxmin qilmasdan eng eskisini olamiz.
        rasmsiz = [c for c in ochiq if not await self._has_batches(session, c.id)]
        tanlangan = (rasmsiz or ochiq)[0]
        nomerlar = ", ".join(
            f"{format_phone_pretty(c.phone)}"
            + (" ←" if c.id == tanlangan.id else "")
            for c in ochiq
        )
        await self.alert_sink(
            f"⚠️ {admin_name}: mijozda {len(ochiq)} ta ochiq nomer bor, rasm esa "
            f"REPLY'siz tashlandi — tizim qaysi biriga tegishli ekanini "
            f"bilmaydi.\n\n"
            f"Nomerlar: {nomerlar}\n"
            f"Rasm ← belgilangan nomerga yozildi.\n\n"
            f"To'g'ri bo'lishi uchun: rasmni mijozning KERAKLI NOMERLI "
            f"xabariga <b>reply</b> qilib tashlang.",
            True,
        )
        return tanlangan

    async def _has_batches(self, session, case_id: int) -> bool:
        row = (
            await session.execute(
                select(ScreenshotBatch.id)
                .where(ScreenshotBatch.case_id == case_id)
                .limit(1)
            )
        ).scalars().first()
        return row is not None

    async def _get_latest_open_case(self, session, user_id: int) -> Case | None:
        result = await session.execute(
            select(Case).where(Case.user_id == user_id).order_by(Case.id.desc())
        )
        case = result.scalars().first()
        if case is None or case.status not in V2_OPEN_STATUSES:
            return None
        return case

    async def _find_previous_batch(
        self,
        session,
        phone: str,
        exclude_case_id: int,
        media_ids: list[int] | None = None,
    ) -> ScreenshotBatch | None:
        """§5.4 — dublikat qidiruvi: NOMER yoki RASM bo'yicha.

        O'sha case'ning o'ziga qayta rasm tashlash dublikat EMAS: §6.1a buni
        normal holat deb belgilaydi ("admin rasmni ikkinchi marta tashlasa —
        taymer oxirgi rasm vaqtidan qayta hisoblanadi"). Avval bu ajratilmagani
        uchun har qayta tashlashda superadminga "ikki admin bitta mijoz ustida
        ishlayapti" degan noto'g'ri alert ketardi va caption o'z case'iga
        havola qilib "avval ham tashlangan" deb yozardi.

        Nomerdan tashqari RASM bo'yicha ham qidiriladi: mijoz nomerni
        o'zgartirib aynan o'sha skrinshotni qayta yuborishi mumkin — bunda
        nomer boshqa bo'lgani uchun birinchi tekshiruv jim qolardi. Media id
        bir xil bo'lsa, bu Telegram'dagi AYNAN o'sha rasm.
        """
        nomer_bo_yicha = (
            await session.execute(
                select(ScreenshotBatch)
                .where(
                    ScreenshotBatch.phone == phone,
                    ScreenshotBatch.case_id != exclude_case_id,
                )
                .order_by(ScreenshotBatch.id.desc())
            )
        ).scalars().first()
        if nomer_bo_yicha is not None:
            return nomer_bo_yicha

        if not media_ids:
            return None

        # Rasm bo'yicha: SQLite'da JSON ro'yxat ichidan qidirish noqulay,
        # shuning uchun boshqa case'lardagi partiyalarni o'qib, to'plamlar
        # kesishmasini tekshiramiz. Partiyalar soni kichik (mijoz kesimida
        # o'nlab), shuning uchun bu qimmat emas.
        yangi = set(media_ids)
        boshqalar = (
            await session.execute(
                select(ScreenshotBatch)
                .where(ScreenshotBatch.case_id != exclude_case_id)
                .order_by(ScreenshotBatch.id.desc())
            )
        ).scalars().all()
        for oldingi in boshqalar:
            try:
                eski = set(json.loads(oldingi.media_ids or "[]"))
            except json.JSONDecodeError:
                continue
            if eski & yangi:
                return oldingi
        return None

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
        """TZ v2 5.2 dagi tasdiqlangan format.

        Caption HTML rejimida yuboriladi (`manual_relay`da `parse_mode="html"`)
        — shuning uchun ichidagi HAR QANDAY foydalanuvchi matni (mijoz ismi,
        username, admin ismi) `html.escape` bilan ekranlanadi. Aks holda
        ismida `<` yoki `&` bo'lgan mijoz butun caption'ni buzardi.
        """
        local_now = to_tashkent(now)
        # TZ v2 5.2 — mijozga BOSILADIGAN havola (`tg://user?id=`). Avval
        # oddiy matn edi: username'i yo'q mijozga nazorat guruhidan o'tishning
        # iloji yo'q edi ("id:6644467393" bosilmaydi).
        ism = user.display_name or (
            f"@{user.tg_username}" if user.tg_username else "mijoz"
        )
        havola = f'<a href="tg://user?id={user.tg_user_id}">{escape(ism)}</a>'
        customer = (
            f"{havola} (@{escape(user.tg_username)})" if user.tg_username else havola
        )
        lines = [
            f"📸 #{case.short_code or case.id}",
            f"👤 {customer}",
            f"📱 {format_phone_pretty(case.phone)}",
            f"🧑‍💼 Admin: {escape(admin_name)}",
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
                f"(Admin: {escape(prev_admin.name) if prev_admin else '?'}, "
                f"{to_tashkent(prev.sent_at):%H:%M})"
            )
        return "\n".join(lines)
