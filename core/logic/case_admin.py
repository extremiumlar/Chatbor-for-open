"""Admin qo'lda aralashuv amallari — TZ 9.3 ("Noaniq natijada: Tasdiqlash /
Rad / Qayta uzatish"), 5.2 (bloklash/blokdan chiqarish), 11.1 (mijozga izoh).

Bu modul faqat BAZANI o'zgartiradi. Mijozga xabar yuborish yoki botga
dispatch qilish Adminbot ichida MUMKIN EMAS — u Telethon'ga ega emas, mijoz
bilan "admin nomidan" faqat Teleton jarayoni gaplasha oladi (TZ 13.1).
Shuning uchun "Qayta uzatish" bayroq qo'yish bilan cheklanadi, haqiqiy
dispatch'ni Teleton'ning fon kuzatuvchisi bajaradi.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import CaseStatus
from core.models import Case, CouponAttempt, User


async def manual_confirm(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — admin noaniq case'ni qo'lda TASDIQLAYDI."""
    case = await session.get(Case, case_id)
    if case is None:
        return None
    case.status = CaseStatus.CONFIRMED
    case.confirmed_at = datetime.datetime.utcnow()
    case.admin_redispatch_requested = False
    await session.commit()
    await session.refresh(case)
    return case


async def manual_reject(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — admin noaniq case'ni qo'lda RAD ETADI."""
    case = await session.get(Case, case_id)
    if case is None:
        return None
    case.status = CaseStatus.REJECTED
    case.admin_redispatch_requested = False
    await session.commit()
    await session.refresh(case)
    return case


async def request_redispatch(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — "Qayta uzatish": case'ni botga qaytadan yuborishni so'raydi.

    Case `NUMBER_RECEIVED`ga qaytariladi va bayroq qo'yiladi; Teleton'ning
    `_admin_redispatch_watcher` fon vazifasi buni ko'rib bo'sh bot tanlaydi
    va mijozdan kuponni qaytadan so'raydi.
    """
    case = await session.get(Case, case_id)
    if case is None:
        return None
    case.status = CaseStatus.NUMBER_RECEIVED
    case.bot_id = None
    case.admin_redispatch_requested = True
    await session.commit()
    await session.refresh(case)
    return case


async def set_user_blocked(session: AsyncSession, user_id: int, blocked: bool) -> User | None:
    """TZ 5.2 — foydalanuvchini bloklash yoki blokdan chiqarish."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.is_blocked = blocked
    if not blocked:
        # Blokdan chiqarilganda shubha bayrog'i ham tozalanadi — aks holda
        # case'lar SUSPICIOUS_HOLD'da qotib qolardi.
        user.is_safe = True
    await session.commit()
    await session.refresh(user)
    return user


async def set_user_safe(session: AsyncSession, user_id: int, safe: bool) -> User | None:
    """TZ 5.2 — shubhali foydalanuvchini "xavfsiz" deb belgilash."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.is_safe = safe
    await session.commit()
    await session.refresh(user)
    return user


async def set_user_note(session: AsyncSession, user_id: int, note: str) -> User | None:
    """TZ 11.1 — mijozga admin izohi (CRM)."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.note = note
    await session.commit()
    await session.refresh(user)
    return user


async def get_case_bundle(
    session: AsyncSession, case_id: int
) -> tuple[Case, User, list[CouponAttempt]] | None:
    """Case kartochkasi uchun hamma narsa bir marta o'qiladi."""
    case = await session.get(Case, case_id)
    if case is None:
        return None
    user = await session.get(User, case.user_id)
    attempts = (
        await session.execute(
            select(CouponAttempt).where(CouponAttempt.case_id == case_id).order_by(CouponAttempt.id)
        )
    ).scalars().all()
    return case, user, list(attempts)


async def list_cases_by_statuses(
    session: AsyncSession, statuses: list[CaseStatus], limit: int = 100
) -> list[Case]:
    result = await session.execute(
        select(Case).where(Case.status.in_(statuses)).order_by(Case.id.desc()).limit(limit)
    )
    return list(result.scalars().all())
