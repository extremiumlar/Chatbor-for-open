"""Umumiy kalit-qiymat tizim sozlamalari — TZ 9.1 (bildirishnoma batafsil
rejimi), 4.1 va 2.2 (audit J-9 — operator kodlari va mijoz-timeout endi
shu yerda, .env'dan faqat BOSHLANG'ICH qiymat sifatida seed qilinadi)."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.models import Setting

NOTIFY_VERBOSE_KEY = "NOTIFY_VERBOSE"
OPERATOR_CODES_KEY = "UZ_OPERATOR_CODES"
CUSTOMER_TIMEOUT_KEY = "CUSTOMER_TIMEOUT_SECONDS"


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    row = await session.get(Setting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def is_verbose(session: AsyncSession) -> bool:
    return await get_setting(session, NOTIFY_VERBOSE_KEY, "0") == "1"


async def set_verbose(session: AsyncSession, value: bool) -> None:
    await set_setting(session, NOTIFY_VERBOSE_KEY, "1" if value else "0")


# --------------------------------------------------------------------------- #
# Audit J-9 (TZ 4.1) — "Operator kodlari ro'yxati adminbot orqali sozlanadi
# (yangi operator qo'shilsa kodni o'zgartirish shart bo'lmasin)." Avval bu
# faqat `.env` + qayta ishga tushirish orqali o'zgartirilardi.
# --------------------------------------------------------------------------- #


async def get_operator_codes(session: AsyncSession) -> list[str]:
    default = ",".join(settings.uz_operator_codes)
    raw = await get_setting(session, OPERATOR_CODES_KEY, default)
    return [code.strip() for code in raw.split(",") if code.strip()]


async def set_operator_codes(session: AsyncSession, codes: list[str]) -> None:
    await set_setting(session, OPERATOR_CODES_KEY, ",".join(codes))


# --------------------------------------------------------------------------- #
# Audit J-9 (TZ 2.2) — "5 daqiqa — adminbot orqali sozlanadigan qiymat."
# Avval bu ham faqat `.env` + qayta ishga tushirish orqali o'zgartirilardi.
# --------------------------------------------------------------------------- #


async def get_customer_timeout_seconds(session: AsyncSession) -> float:
    default = str(settings.customer_coupon_timeout_seconds)
    raw = await get_setting(session, CUSTOMER_TIMEOUT_KEY, default)
    try:
        return float(raw)
    except ValueError:
        return settings.customer_coupon_timeout_seconds


async def set_customer_timeout_seconds(session: AsyncSession, seconds: float) -> None:
    if seconds <= 0:
        raise ValueError("Kutish vaqti musbat bo'lishi kerak.")
    await set_setting(session, CUSTOMER_TIMEOUT_KEY, str(seconds))
