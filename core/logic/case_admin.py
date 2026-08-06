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

from core.enums import CaseStatus, MANUAL_RESOLVABLE_STATUSES
from core.models import Case, CouponAttempt, User


class InvalidCaseStateError(Exception):
    """Audit K-3 — case topildi, lekin joriy holati bu qo'lda amal uchun
    mos emas (masalan hali faol ishlanayotgan yoki SUSPICIOUS_HOLD'da,
    o'zining alohida Xavfsiz/Bloklash oqimi bor). Chaqiruvchi (Adminbot)
    buni "case topilmadi"dan farqlab, kartochkani yangilab ko'rsatishi kerak.
    """

    def __init__(self, case: Case) -> None:
        self.case = case
        super().__init__(f"Case #{case.id} holati ({case.status.value}) bu amalga mos emas.")


async def manual_confirm(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — admin noaniq case'ni qo'lda TASDIQLAYDI.

    Audit K-3 — faqat `MANUAL_RESOLVABLE_STATUSES`dagi case'lar uchun
    ishlaydi (server tomonida tekshiriladi, faqat tugma ko'rinishiga
    tayanilmaydi) — aks holda hali botga hech qanday real tekshiruvga
    yuborilmagan yoki allaqachon yopilgan case eskirgan/soxta tugma bosilib
    "tasdiqlangan" deb belgilanib qolishi mumkin edi.
    """
    case = await session.get(Case, case_id)
    if case is None:
        return None
    if case.status not in MANUAL_RESOLVABLE_STATUSES:
        raise InvalidCaseStateError(case)
    case.status = CaseStatus.CONFIRMED
    case.confirmed_at = datetime.datetime.utcnow()
    case.admin_redispatch_requested = False
    await session.commit()
    await session.refresh(case)
    return case


async def manual_reject(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — admin noaniq case'ni qo'lda RAD ETADI. Audit K-3: yuqoridagi
    `manual_confirm` bilan bir xil holat-tekshiruvi."""
    case = await session.get(Case, case_id)
    if case is None:
        return None
    if case.status not in MANUAL_RESOLVABLE_STATUSES:
        raise InvalidCaseStateError(case)
    case.status = CaseStatus.REJECTED
    case.admin_redispatch_requested = False
    await session.commit()
    await session.refresh(case)
    return case


async def request_redispatch(session: AsyncSession, case_id: int) -> Case | None:
    """TZ 9.3 — "Qayta uzatish": case'ni botga qaytadan yuborishni so'raydi.

    Case `NUMBER_RECEIVED`ga qaytariladi va bayroq qo'yiladi; Teleton'ning
    `_admin_redispatch_watcher` fon vazifasi buni ko'rib bo'sh bot tanlaydi
    va mijozdan kuponni qaytadan so'raydi. Audit K-3: yuqoridagilar bilan
    bir xil holat-tekshiruvi.
    """
    case = await session.get(Case, case_id)
    if case is None:
        return None
    if case.status not in MANUAL_RESOLVABLE_STATUSES:
        raise InvalidCaseStateError(case)
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


# --------------------------------------------------------------------------- #
# Audit K-4/J-8 — TZ 11.0 (Q51, TASDIQLANGAN): oddiy admin faqat o'ziga
# biriktirilgan (yoki hali hech kimga biriktirilmagan) mijoz/case'larni
# ko'radi. Biriktirish `User.assigned_admin_id` orqali — case emas, MIJOZ
# darajasida (TZ 11.1), chunki bitta mijozning barcha case'lari bir xil
# admin bilan ishlashi kerak.
# --------------------------------------------------------------------------- #


async def assign_customer(session: AsyncSession, user_id: int, admin_id: int | None) -> User | None:
    """Mijozni ma'lum adminga biriktiradi (yoki `admin_id=None` bilan
    "hech kimga biriktirilmagan" holatga qaytaradi)."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.assigned_admin_id = admin_id
    await session.commit()
    await session.refresh(user)
    return user


def _visible_to(stmt, viewer_admin_id: int, can_see_all: bool):
    """`users`ga JOIN qilingan so'rovga ko'rish-cheklash sharti qo'shadi.

    `can_see_all=True` (Owner/Rop) bo'lsa hech narsa cheklamaydi. Aks holda
    faqat hali hech kimga biriktirilmagan (`assigned_admin_id IS NULL`) YOKI
    aynan shu adminga biriktirilgan qatorlarni qoldiradi.
    """
    if can_see_all:
        return stmt
    return stmt.where(
        (User.assigned_admin_id.is_(None)) | (User.assigned_admin_id == viewer_admin_id)
    )


async def get_case_bundle(
    session: AsyncSession,
    case_id: int,
    viewer_admin_id: int | None = None,
    can_see_all: bool = True,
) -> tuple[Case, User, list[CouponAttempt]] | None:
    """Case kartochkasi uchun hamma narsa bir marta o'qiladi.

    Audit K-4 — `can_see_all=False` bo'lsa va mijoz BOSHQA adminga
    biriktirilgan bo'lsa, `None` qaytaradi (topilmadi bilan bir xil javob —
    boshqa adminning mijozi borligini oshkor qilmaslik uchun ham to'g'ri).
    """
    case = await session.get(Case, case_id)
    if case is None:
        return None
    user = await session.get(User, case.user_id)
    if not can_see_all and user is not None:
        if user.assigned_admin_id is not None and user.assigned_admin_id != viewer_admin_id:
            return None
    attempts = (
        await session.execute(
            select(CouponAttempt).where(CouponAttempt.case_id == case_id).order_by(CouponAttempt.id)
        )
    ).scalars().all()
    return case, user, list(attempts)


async def list_cases_by_statuses(
    session: AsyncSession,
    statuses: list[CaseStatus],
    limit: int = 100,
    viewer_admin_id: int | None = None,
    can_see_all: bool = True,
) -> list[Case]:
    stmt = select(Case).where(Case.status.in_(statuses))
    if not can_see_all:
        stmt = stmt.join(User, Case.user_id == User.id)
        stmt = _visible_to(stmt, viewer_admin_id, can_see_all)
    stmt = stmt.order_by(Case.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
