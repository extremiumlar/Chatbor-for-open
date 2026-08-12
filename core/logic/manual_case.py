"""v2 holat mashinasi — TZ v2 (Qo'lda Admin Oqimi) 3/6-bo'lim, B-1 qamrovi.

v1 `case_manager.CaseManager`dan tub farqlari:
- Tekshiruv bot pool YO'Q — tekshiruv B-3'da tekshiruvchi lichka orqali.
- Kupon TEKSHIRILMAYDI — faqat mijoz-holati signali sifatida saqlanadi
  (kupon bor = ovoz bergan; TZ v2 9.2).
- Har case aniq bitta adminga biriktiriladi (`assigned_admin_id`) — nomer
  qaysi adminning lichkasiga kelgan bo'lsa, o'sha (TZ v2 4.2).
- Mijozga avtomatik javob deyarli yo'q — admin tabiiy suhbatda o'zi yozadi;
  tizim faqat ALREADY_CONFIRMED holatida shablon qaytaradi (TZ v2 6.1 a4).
- Taymerlar xotirada emas — `scheduled_jobs` jadvalida (TZ v2 9.4), ularni
  B-3'dagi poller bajaradi.

B-1 qamrovga KIRMAYDI (keyingi bosqichlar): rasm partiyasi (B-2), tekshiruv
dvigateli/drip/javob tanish (B-3), natija tarqatish (B-4).
"""

import datetime
import json
import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select

from core.enums import CaseStatus, V2_OPEN_STATUSES
from core.logic.settings_store import get_no_screenshot_first_minutes
from core.logic.templates import get_template
from core.models import Case, JobKind, ScheduledJob, User

log = logging.getLogger("manual_case")


@dataclass
class ManualOutcome:
    """Hodisa natijasi: mijozga darhol yuboriladigan matn (bo'lsa) va case."""

    customer_text: str | None = None
    case: Case | None = None


async def _default_alert(message: str, important: bool = True) -> None:
    log.info("ADMIN ALERT: %s", message)


async def _default_suspicious_alert(
    message: str, case_id: int, tg_user_id: int, tg_username: str | None
) -> None:
    log.warning("SUSPICIOUS ALERT (case #%s): %s", case_id, message)


class ManualCaseManager:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        alert_sink: Callable[[str, bool], Awaitable[None]] = _default_alert,
        suspicious_alert_sink: Callable[
            [str, int, int, str | None], Awaitable[None]
        ] = _default_suspicious_alert,
    ) -> None:
        self.session_factory = session_factory
        self.alert_sink = alert_sink
        self.suspicious_alert_sink = suspicious_alert_sink

    # ------------------------------------------------------------------ #
    # Kiruvchi hodisalar (manual_relay shu metodlarni chaqiradi)
    # ------------------------------------------------------------------ #

    async def handle_phone_detected(
        self,
        admin_id: int,
        tg_user_id: int,
        tg_username: str | None,
        display_name: str | None,
        phone: str,
    ) -> ManualOutcome:
        """Mijoz lichkasida nomer aniqlanganda (TZ v2 3-bo'lim, T0)."""
        async with self.session_factory() as session:
            user = await self._get_or_create_user(
                session, tg_user_id, tg_username, display_name
            )

            if user.is_blocked:
                # v1 merosidagi bloklash saqlanadi — bloklangan mijoz jim
                # e'tiborsiz qoldiriladi.
                return ManualOutcome()

            latest_case = await self._get_latest_case(session, user.id)

            if latest_case is not None and latest_case.status in V2_OPEN_STATUSES:
                if latest_case.phone == phone:
                    # O'sha nomer jarayon davomida qayta yozildi — oddiy suhbat,
                    # tizim aralashmaydi (admin o'zi ko'radi).
                    return ManualOutcome(case=latest_case)
                # Ochiq case turganda BOSHQA nomer keldi — mijozga tizim hech
                # narsa yozmaydi (admin tabiiy suhbatda o'zi hal qiladi), lekin
                # admin adashib ikki jarayon ochib yubormasligi uchun alert.
                await self._alert(
                    f"Mijoz (tg_id={tg_user_id}) ikkinchi nomer yubordi ({phone}), "
                    f"lekin {latest_case.short_code or f'#{latest_case.id}'} "
                    f"({latest_case.phone}) hali ochiq "
                    f"({latest_case.status.value}).",
                    important=True,
                )
                return ManualOutcome(case=latest_case)

            passed_case = await self._find_passed_case_by_phone(session, phone)
            if passed_case is not None:
                if passed_case.user_id != user.id:
                    # Tasdiqlangan nomerni BOSHQA akkaunt yubordi — kuchli
                    # firibgarlik signali (v1 Audit O-1 mantiqi saqlanadi).
                    return await self._hold_as_suspicious(
                        session, user, admin_id, phone, passed_case
                    )
                # TZ v2 6.1 a4 — "O'TDI abadiy": o'zi qayta yuborsa shablon javob,
                # tekshiruvchi bezovta qilinmaydi.
                text = await get_template(session, "ALREADY_CONFIRMED")
                return ManualOutcome(customer_text=text, case=passed_case)

            other_case = await self._find_other_users_case_by_phone(session, phone, user.id)
            if other_case is not None:
                # TZ v2 12-bo'lim — "bir nomer turli akkauntdan" shubhali
                # mantiq v1'dan saqlanadi.
                return await self._hold_as_suspicious(
                    session, user, admin_id, phone, other_case
                )

            return await self._open_new_case(session, user, admin_id, phone)

    async def handle_coupon_detected(self, tg_user_id: int, coupon: str) -> None:
        """Mijoz kupon raqamini yozganda — FAQAT saqlanadi (TZ v2 9.2).

        Hech qanday tekshiruv, hech qanday javob yo'q: kupon "mijoz ovoz
        bergan" signali va dalil. Ochiq case bo'lmasa, e'tiborsiz qoldiriladi
        (oddiy suhbatdagi 6 xonali son bo'lishi mumkin).
        """
        async with self.session_factory() as session:
            user = await self._get_user(session, tg_user_id)
            if user is None or user.is_blocked:
                return

            case = await self._get_latest_case(session, user.id)
            if case is None or case.status not in V2_OPEN_STATUSES:
                return
            if case.coupon is not None:
                return  # birinchi kupon saqlangan — keyingilari e'tiborsiz

            case.coupon = coupon
            case.coupon_at = datetime.datetime.utcnow()
            await session.commit()
            log.info(
                "Case %s uchun kupon saqlandi (signal: mijoz ovoz bergan).",
                case.short_code or case.id,
            )

    # ------------------------------------------------------------------ #
    # Ichki yordamchilar
    # ------------------------------------------------------------------ #

    async def _open_new_case(
        self, session, user: User, admin_id: int, phone: str
    ) -> ManualOutcome:
        case = Case(
            user_id=user.id,
            phone=phone,
            status=CaseStatus.NUMBER_RECEIVED,
            assigned_admin_id=admin_id,
        )
        session.add(case)
        await session.commit()
        await session.refresh(case)

        # TZ v2 9.2 — qisqa kod id'dan keyin to'ldiriladi ("C1247").
        case.short_code = f"C{case.id}"

        # TZ v2 6.1 a2 — rasmsizlik kuzatuvi darhol rejalashtiriladi
        # (bazada — restart'dan omon qoladi, TZ v2 9.4). Tekshiruv taymeri
        # (CHECK_DUE) esa faqat admin rasm tashlaganda ochiladi (B-2).
        first_minutes = await get_no_screenshot_first_minutes(session)
        session.add(
            ScheduledJob(
                kind=JobKind.REMIND_NO_SCREENSHOT,
                case_id=case.id,
                due_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=first_minutes),
                payload=json.dumps({"reminder_no": 1}),
            )
        )
        await session.commit()
        await session.refresh(case)

        log.info(
            "Yangi case %s: nomer %s, admin_id=%s, tg_id=%s.",
            case.short_code,
            phone,
            admin_id,
            user.tg_user_id,
        )
        return ManualOutcome(case=case)

    async def _hold_as_suspicious(
        self, session, user: User, admin_id: int, phone: str, other_case: Case
    ) -> ManualOutcome:
        case = Case(
            user_id=user.id,
            phone=phone,
            status=CaseStatus.SUSPICIOUS_HOLD,
            assigned_admin_id=admin_id,
        )
        session.add(case)
        user.is_safe = False
        await session.commit()
        await session.refresh(case)
        case.short_code = f"C{case.id}"
        await session.commit()

        await self.suspicious_alert_sink(
            f"SHUBHALI: nomer {phone} boshqa akkauntdan ham kelgan "
            f"(oldingi user_id={other_case.user_id}, "
            f"{other_case.short_code or f'#{other_case.id}'}). "
            f"Joriy: tg_id={user.tg_user_id}, @{user.tg_username or '-'}.",
            case.id,
            user.tg_user_id,
            user.tg_username,
        )
        # Mijozga hech narsa yozilmaydi (tergovni oshkor qilmaslik).
        return ManualOutcome(case=case)

    async def _alert(self, message: str, important: bool = True) -> None:
        await self.alert_sink(message, important)

    async def _get_or_create_user(
        self, session, tg_user_id: int, tg_username: str | None, display_name: str | None
    ) -> User:
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        user = result.scalars().first()
        if user is None:
            user = User(
                tg_user_id=tg_user_id, tg_username=tg_username, display_name=display_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    async def _get_user(self, session, tg_user_id: int) -> User | None:
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        return result.scalars().first()

    async def _get_latest_case(self, session, user_id: int) -> Case | None:
        # id bo'yicha tartib — SQLite CURRENT_TIMESTAMP soniya aniqligida
        # (v1 dagi bilan bir xil sabab).
        result = await session.execute(
            select(Case).where(Case.user_id == user_id).order_by(Case.id.desc())
        )
        return result.scalars().first()

    async def _find_passed_case_by_phone(self, session, phone: str) -> Case | None:
        # v2 PASSED bilan birga v1 davridagi CONFIRMED ham "o'tgan" sanaladi —
        # eski bazadagi tasdiqlangan nomerlar himoyasi yo'qolib qolmasin.
        result = await session.execute(
            select(Case).where(
                Case.phone == phone,
                Case.status.in_([CaseStatus.PASSED, CaseStatus.CONFIRMED]),
            )
        )
        return result.scalars().first()

    async def _find_other_users_case_by_phone(
        self, session, phone: str, exclude_user_id: int
    ) -> Case | None:
        result = await session.execute(
            select(Case)
            .where(Case.phone == phone, Case.user_id != exclude_user_id)
            .order_by(Case.id.desc())
        )
        return result.scalars().first()
