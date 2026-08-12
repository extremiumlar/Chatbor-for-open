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


# --------------------------------------------------------------------------- #
# TZ v2 (Qo'lda Admin Oqimi) 10-bo'lim — jonli sozlamalar. `.env` faqat
# boshlang'ich qiymat; adminbot orqali o'zgartirilgani darhol ta'sir qiladi.
# --------------------------------------------------------------------------- #

NO_SCREENSHOT_FIRST_KEY = "NO_SCREENSHOT_FIRST_MINUTES"
NO_SCREENSHOT_REMINDERS_KEY = "NO_SCREENSHOT_REMINDERS"
CHECK_DELAY_KEY = "CHECK_DELAY_MINUTES"
GROUP_CHAT_ID_KEY = "GROUP_CHAT_ID"
IMAGE_BATCH_WINDOW_KEY = "IMAGE_BATCH_WINDOW_SECONDS"


async def _get_int_setting(session: AsyncSession, key: str, default: int) -> int:
    raw = await get_setting(session, key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


async def get_no_screenshot_first_minutes(session: AsyncSession) -> int:
    return await _get_int_setting(
        session, NO_SCREENSHOT_FIRST_KEY, settings.no_screenshot_first_minutes
    )


async def get_no_screenshot_reminders(session: AsyncSession) -> int:
    return await _get_int_setting(
        session, NO_SCREENSHOT_REMINDERS_KEY, settings.no_screenshot_reminders
    )


async def get_check_delay_minutes(session: AsyncSession) -> int:
    return await _get_int_setting(session, CHECK_DELAY_KEY, settings.check_delay_minutes)


async def get_group_chat_id(session: AsyncSession) -> int | None:
    """TZ v2 5.2 — nazorat guruhi. Sozlanmagan bo'lsa None (rasmlar bazaga
    yoziladi, guruhga tushmaydi, superadminga alert — §5.5)."""
    raw = await get_setting(session, GROUP_CHAT_ID_KEY, "")
    try:
        return int(raw) if raw.strip() else None
    except ValueError:
        return None


async def set_group_chat_id(session: AsyncSession, chat_id: int) -> None:
    await set_setting(session, GROUP_CHAT_ID_KEY, str(chat_id))


async def get_image_batch_window_seconds(session: AsyncSession) -> float:
    raw = await get_setting(
        session, IMAGE_BATCH_WINDOW_KEY, str(settings.image_batch_window_seconds)
    )
    try:
        return float(raw)
    except ValueError:
        return settings.image_batch_window_seconds


# --------------------------------------------------------------------------- #
# TZ v2 6-bo'lim — tekshiruv dvigateli sozlamalari (B-3)
# --------------------------------------------------------------------------- #

CHECKER_ACCOUNT_KEY = "CHECKER_ACCOUNT"
DRIP_INTERVAL_KEY = "DRIP_INTERVAL_SECONDS"
CHECKER_STALL_KEY = "CHECKER_STALL_MINUTES"
CHECK_CACHE_KEY = "CHECK_CACHE_MINUTES"
SHADOW_MODE_KEY = "SHADOW_MODE"
CHECK_REQUEST_TEMPLATE_KEY = "CHECK_REQUEST_TEMPLATE"


async def get_checker_account(session: AsyncSession) -> str | None:
    """Tekshiruvchi lichka (username yoki raqamli id). Sozlanmagan bo'lsa
    None — tekshiruv dvigateli ishga tushmaydi (§6.4.7 ruhida)."""
    raw = await get_setting(session, CHECKER_ACCOUNT_KEY, "")
    return raw.strip() or None


async def set_checker_account(session: AsyncSession, value: str) -> None:
    await set_setting(session, CHECKER_ACCOUNT_KEY, value.strip().lstrip("@"))


async def get_drip_interval_seconds(session: AsyncSession) -> float:
    raw = await get_setting(session, DRIP_INTERVAL_KEY, "20")
    try:
        return float(raw)
    except ValueError:
        return 20.0


async def get_checker_stall_minutes(session: AsyncSession) -> int:
    return await _get_int_setting(session, CHECKER_STALL_KEY, 30)


async def get_check_cache_minutes(session: AsyncSession) -> int:
    return await _get_int_setting(session, CHECK_CACHE_KEY, 10)


async def is_shadow_mode(session: AsyncSession) -> bool:
    """TZ v2 6.4.6 — soya rejimi STANDART YOQILGAN: tizim tanib oladi,
    bazaga yozadi, lekin mijozga hech narsa yozmaydi (B-4 shu bayroqqa
    qaraydi). Jonli rejimga adminbot orqali o'tiladi."""
    return await get_setting(session, SHADOW_MODE_KEY, "1") == "1"


async def set_shadow_mode(session: AsyncSession, value: bool) -> None:
    await set_setting(session, SHADOW_MODE_KEY, "1" if value else "0")


DAILY_REPORT_TIME_KEY = "DAILY_REPORT_TIME"


async def get_daily_report_time(session: AsyncSession) -> str:
    """TZ v2 8.1 — kunlik hisobot vaqti (Toshkent, HH:MM)."""
    return await get_setting(session, DAILY_REPORT_TIME_KEY, "21:00")


async def get_check_request_template(session: AsyncSession) -> str:
    """Tekshiruvchiga yuboriladigan xabar shakli. `{phone}` o'rniga kanonik
    nomer qo'yiladi. Format masalasi keyinga qoldirilgan (TZ 15.1) —
    standart oddiy "+998...", adminbot orqali o'zgartiriladi."""
    return await get_setting(session, CHECK_REQUEST_TEMPLATE_KEY, "+{phone}")
