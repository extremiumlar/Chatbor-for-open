"""Admin harakatlari tarixi — TZ 11.5, 12.2 (kim, qachon, nima qildi).

Faqat HOLAT O'ZGARTIRUVCHI (mutating) buyruqlar yoziladi (shablon
o'zgartirish, bot qo'shish, bildirishnoma rejimini almashtirish, shubhali
holatni xavfsiz/bloklash deb belgilash) — o'qish uchun buyruqlar
(`/bots`, `/templates`, `/pending`, `/problems`, `drop find`) audit talab
qilmaydi, chunki ular hech narsani o'zgartirmaydi.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import AuditLog


async def log_action(session: AsyncSession, admin_tg_id: int, action: str, details: str = "") -> None:
    session.add(AuditLog(admin_tg_id=admin_tg_id, action=action, details=details))
    await session.commit()


async def list_recent(session: AsyncSession, limit: int = 20) -> list[AuditLog]:
    result = await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return list(result.scalars().all())
