"""Admin ro'yxati va kirish nazorati — TZ 12.2 (faqat `admins` jadvalidagi
Telegram ID-lar Adminbotga buyruq bera oladi), 14-bo'lim (rollar, Q51).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logic.audit import log_action
from core.models import Admin, AdminRole, AdminSession, UNRESTRICTED_ROLES

log = logging.getLogger("admins")


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

    await ensure_owner_exists(session, tg_ids)


async def ensure_owner_exists(session: AsyncSession, tg_ids: list[int]) -> Admin | None:
    """Tizimda kamida bitta FAOL OWNER borligini kafolatlaydi.

    Nega kerak: rol berish (`/setrole`) faqat OWNER'ga ochiq. Agar yagona
    OWNER boshqa rolga o'tkazilsa yoki nofaol qilinsa, hech kim rol bera
    olmay qoladi va tizim butunlay qulflanadi — buni ichkaridan tuzatib
    bo'lmaydi. Shu sababli ishga tushishda OWNER yo'qligi aniqlansa,
    `.env`dagi ADMIN_TG_IDS ro'yxatining birinchisi OWNER'ga ko'tariladi.

    Qaytaradi: ko'tarilgan admin (agar ko'tarish bo'lgan bo'lsa), aks holda None.
    """
    result = await session.execute(
        select(Admin).where(Admin.role == AdminRole.OWNER, Admin.is_active.is_(True))
    )
    if result.scalars().first() is not None:
        return None

    for tg_id in tg_ids:
        candidate = (
            await session.execute(select(Admin).where(Admin.tg_user_id == tg_id))
        ).scalars().first()
        if candidate is not None:
            eski_rol = candidate.role.value
            candidate.role = AdminRole.OWNER
            candidate.is_active = True
            await session.commit()
            await session.refresh(candidate)
            # Audit jurnaliga YOZILADI: avval bu faqat log faylida qolar edi.
            # Jonli sinovda foydalanuvchi `/setrole ... DASTURCHI` bajarib
            # tasdiq oldi, keyingi restartda esa rol jimgina OWNER'ga qaytdi
            # va u o'zini DASTURCHI deb o'ylab yurdi. Mexanizmning o'zi
            # to'g'ri (tizim qulflanmasligi uchun kerak) — faqat ko'rinishi
            # yetishmasdi.
            await log_action(
                session,
                candidate.tg_user_id,
                "auto_promote_owner",
                f"{eski_rol} -> OWNER (tizimda faol OWNER qolmagan edi)",
            )
            log.warning(
                "Tizimda faol OWNER topilmadi — %s (tg_id=%s) %s rolidan "
                "OWNER'ga ko'tarildi. Aks holda hech kim /setrole ishlata "
                "olmay, tizim qulflanib qolardi.",
                candidate.name,
                candidate.tg_user_id,
                eski_rol,
            )
            return candidate

    log.error(
        "Tizimda OWNER yo'q va .env ADMIN_TG_IDS'dagi hech kim bazada topilmadi — "
        "rol boshqaruvi ishlamaydi. ADMIN_TG_IDS'ni tekshiring."
    )
    return None


async def is_last_active_owner(session: AsyncSession, admin_id: int) -> bool:
    """Shu admin tizimdagi YAGONA faol OWNER'mi.

    `/setrole` shuni oldindan aytishi uchun kerak: yagona Owner o'zini
    pasaytirsa, `ensure_owner_exists` keyingi ishga tushishda uni jimgina
    qaytarib ko'taradi va u o'zini yangi rolda deb o'ylab yuradi.
    """
    result = await session.execute(
        select(Admin.id).where(Admin.role == AdminRole.OWNER, Admin.is_active.is_(True))
    )
    owner_ids = [row[0] for row in result.all()]
    return owner_ids == [admin_id]


def display_name(admin: Admin) -> str:
    """Ro'yxatlarda ko'rsatiladigan "kim ekani" — imkon qadar tushunarli.

    Tartib: to'liq ism (@username) → username → ism → tg_id. Seed paytida
    `name` faqat raqam bo'lgani uchun, u yagona ma'lumot bo'lsa ham hech
    bo'lmasa raqam ko'rinadi.
    """
    full = (admin.full_name or "").strip()
    uname = (admin.tg_username or "").strip()

    if full and uname:
        return f"{full} (@{uname})"
    if full:
        return full
    if uname:
        return f"@{uname}"
    if admin.name and admin.name != str(admin.tg_user_id):
        return admin.name
    return f"id:{admin.tg_user_id}"


async def refresh_admin_identity(
    session: AsyncSession,
    admin: Admin,
    full_name: str | None,
    username: str | None,
) -> bool:
    """Telegram'dagi joriy ism/username bilan yangilaydi (o'zgargan bo'lsa).

    Har muloqotda chaqiriladi: admin ismini o'zgartirsa yoki username
    olsa, ro'yxat o'z-o'zidan yangilanadi — qo'lda kiritish shart emas.
    Qaytaradi: yozildimi (test va ortiqcha commit'dan qochish uchun).
    """
    changed = False
    if full_name and admin.full_name != full_name:
        admin.full_name = full_name
        changed = True
    if username != admin.tg_username:
        admin.tg_username = username
        changed = True
    # Eski `name` hali raqam bo'lsa — endi tushunarli nomga almashtiramiz.
    if full_name and admin.name == str(admin.tg_user_id):
        admin.name = full_name
        changed = True
    if changed:
        await session.commit()
    return changed


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


async def list_admin_sessions(session: AsyncSession) -> list[tuple[AdminSession, Admin]]:
    """Har sessiya + egasi — TZ v2 4.3 ("Sessiyalar" ko'rish oynasi uchun).

    Nega INNER JOIN: egasi o'chirilgan sessiya baribir ishlamaydi (Telethon
    klienti admin qatoriga bog'lab ko'tariladi), shuning uchun uni ro'yxatda
    ko'rsatishning ma'nosi yo'q. Nofaol adminlar esa QOLADI — aynan ular
    "nega bu akkaunt jim?" degan savolga javob beradi.
    """
    result = await session.execute(
        select(AdminSession, Admin)
        .join(Admin, AdminSession.admin_id == Admin.id)
        .order_by(Admin.id)
    )
    return [(s, a) for s, a in result.all()]
