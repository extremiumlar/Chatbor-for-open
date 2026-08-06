"""Admin ro'yxati va kirish nazorati — TZ 12.2 (faqat `admins` jadvalidagi
Telegram ID-lar Adminbotga buyruq bera oladi), 14-bo'lim (rollar, Q51).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Admin, AdminRole, UNRESTRICTED_ROLES


async def ensure_admins_seeded(session: AsyncSession, tg_ids: list[int]) -> None:
    """.env dagi ADMIN_TG_IDS bilan boshlang'ich admin ro'yxatini to'ldiradi
    (idempotent).

    Audit K-4/J-8 — tizimda kamida bitta cheklovsiz (OWNER) admin bo'lishi
    kafolatlanishi kerak, aks holda Q51'dagi ko'rish-cheklovi hech kimga
    to'liq ko'rinishni qoldirmay qo'yardi. Ro'yxatdagi (bazada hali
    umuman admin yo'q holatdagi) BIRINCHI tg_id OWNER bo'lib seed qilinadi,
    qolganlari standart ADMIN (eng cheklangan) bo'lib qo'shiladi. Bazada
    allaqachon kamida bitta admin bo'lsa, yangi qo'shilayotganlar ham oddiy
    ADMIN bo'ladi (OWNER faqat "bazada birinchi marta" holatida beriladi).
    """
    result = await session.execute(select(Admin.tg_user_id))
    existing = {row[0] for row in result.all()}
    bootstrap_owner = not existing  # bazada hali birorta ham admin yo'q
    for tg_id in tg_ids:
        if tg_id not in existing:
            role = AdminRole.OWNER if bootstrap_owner else AdminRole.ADMIN
            session.add(Admin(tg_user_id=tg_id, name=str(tg_id), role=role))
            bootstrap_owner = False
    await session.commit()


async def is_admin(session: AsyncSession, tg_user_id: int) -> bool:
    result = await session.execute(select(Admin.id).where(Admin.tg_user_id == tg_user_id))
    return result.scalars().first() is not None


async def get_admin_by_tg_id(session: AsyncSession, tg_user_id: int) -> Admin | None:
    """Audit K-4 — ko'rish-cheklash qoidasi uchun joriy adminning
    id+rolini olish (`IsAdmin` filtri faqat bool qaytarardi)."""
    result = await session.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
    return result.scalars().first()


def can_see_everything(admin: Admin) -> bool:
    """TZ 11.0 (Q51) — Owner/Rop hammasini ko'radi, qolganlari faqat
    o'ziga biriktirilganini (yoki hali biriktirilmaganini)."""
    return admin.role in UNRESTRICTED_ROLES


async def list_admins(session: AsyncSession) -> list[Admin]:
    result = await session.execute(select(Admin).order_by(Admin.id))
    return list(result.scalars().all())


async def set_admin_role(session: AsyncSession, admin_id: int, role: AdminRole) -> Admin | None:
    admin = await session.get(Admin, admin_id)
    if admin is None:
        return None
    admin.role = role
    await session.commit()
    await session.refresh(admin)
    return admin


async def list_admin_tg_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(Admin.tg_user_id))
    return [row[0] for row in result.all()]
