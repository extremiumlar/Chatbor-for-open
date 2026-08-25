"""Mijozga yuboriladigan shablonlar — TZ 7.2, 9.2 (`/templates`).

Adminbot va Teleton alohida jarayon bo'lgani uchun (TZ 13.1) shablonlar
xotirada keshlanmaydi — har chaqiriqda bazadan o'qiladi, shunda bir jarayonda
qilingan o'zgarish ikkinchisiga darhol ko'rinadi.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import texts
from core.models import Template

# TZ 7.2 dagi 7 ta shablon turi. Boshlang'ich qiymatlar core/texts.py'dan.
DEFAULTS: dict[str, str] = {
    "COUPON_REQUEST": texts.COUPON_REQUEST,
    "CONFIRMED": texts.CONFIRMED,
    "REJECTED": texts.REJECTED,
    "EXPIRED_RETRY": texts.EXPIRED_RETRY,
    "IMAGE_INSTEAD_OF_TEXT": texts.IMAGE_INSTEAD_OF_TEXT,
    "DUPLICATE_ACTIVE": texts.DUPLICATE_ACTIVE,
    "ALREADY_CONFIRMED": texts.ALREADY_CONFIRMED,
    "DUPLICATE_COUPON": texts.DUPLICATE_COUPON,
    # TZ v2 5.3 — rasm partiyasidan keyin mijozga tushadigan matn.
    "SCREENSHOT_FOLLOWUP": texts.SCREENSHOT_FOLLOWUP,
    # TZ v2 7.2 — natija matnlari (aralash rejim).
    "RESULT_PASSED": texts.RESULT_PASSED,
    "RESULT_FAILED": texts.RESULT_FAILED,
}


# --------------------------------------------------------------------------- #
# Qaysi shablon HAQIQATAN ishlatiladi (TZ v2 — qo'lda admin oqimi)
# --------------------------------------------------------------------------- #
#
# v1 (avtomatik bot tekshiruvi) davridan 7 ta shablon qolgan. v2 da mijoz
# bilan faqat admin gaplashadi, tizim esa to'rt joyda yozadi — qolganlari
# hech qachon yuborilmaydi.
#
# Nega bu muhim: ro'yxat ularni birdek ko'rsatsa, admin o'lik shablonni
# tahrirlab, matnim nega chiqmayapti deb ovora bo'ladi. Jonli sinovda aynan
# shunday bo'ldi — `CONFIRMED` "Ovozingiz oldim 1,5 soatda eslating" deb
# tahrirlangan, lekin u v2 da umuman yuborilmaydi; kerak bo'lgani
# `SCREENSHOT_FOLLOWUP` edi.
#
# DIQQAT: o'lik shablonlar O'CHIRILMAYDI — v1 kodi (`core/logic/case_manager.py`,
# `teleton_service/relay.py`) ularga hali murojaat qiladi va o'chirilsa
# `KeyError` bilan yiqilardi. Ular faqat ro'yxatda ajratib ko'rsatiladi.
#
# Bu ro'yxatning kod bilan mosligini `tests/test_templates_usage.py`
# tekshiradi — qo'lda yozilgan ro'yxat ertami-kech chetlashadi.

V2_ACTIVE_KEYS: tuple[str, ...] = (
    "SCREENSHOT_FOLLOWUP",   # §5.3 — admin rasm tashlagach
    "ALREADY_CONFIRMED",     # §6.1a4 — nomer allaqachon o'tgan
    "RESULT_PASSED",         # §7.2 — o'tdi (avtomatik)
    "RESULT_FAILED",         # §7.2 — o'tmadi (admin tasdiqlagach)
    # Quyidagilar v1 merosi edi va TZ v2 ularni ATAYLAB jim qoldirgandi
    # ("admin o'zi gaplashadi"). Foydalanuvchi qaroriga ko'ra yoqildi —
    # matnlari allaqachon yozilgan, faqat yuborilmasdi.
    "DUPLICATE_COUPON",      # case'da allaqachon BOSHQA kupon bo'lsa
    "IMAGE_INSTEAD_OF_TEXT",  # nomer matn emas, rasm/ovoz bilan kelsa
    # DUPLICATE_ACTIVE bir muddat shu ro'yxatda edi, lekin keyin oqim
    # o'zgardi: mijozning ikkinchi nomeri endi RAD ETILMAYDI, o'z case'ini
    # oladi (`manual_case.handle_phone_detected`). Ya'ni "oldingi
    # so'rovingiz hali tugamagan" matni endi YOLG'ON bo'lardi — ikkala
    # nomer ham navbatda. Shuning uchun u yana o'lik ro'yxatga qaytdi.
    # (v1 oqimida — `case_manager.py` — hali ishlatiladi.)
)

V2_LEGACY_KEYS: tuple[str, ...] = tuple(
    k for k in DEFAULTS if k not in V2_ACTIVE_KEYS
)


def is_active(key: str) -> bool:
    """Shablon v2 oqimida mijozga yuboriladimi."""
    return key in V2_ACTIVE_KEYS


async def ensure_templates_seeded(session: AsyncSession) -> None:
    result = await session.execute(select(Template.key))
    existing = {row[0] for row in result.all()}
    for key, value in DEFAULTS.items():
        if key not in existing:
            session.add(Template(key=key, value=value))
    await session.commit()


async def get_template(session: AsyncSession, key: str) -> str:
    row = await session.get(Template, key)
    if row is not None:
        return row.value
    return DEFAULTS[key]


async def set_template(session: AsyncSession, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"Noma'lum shablon kaliti: {key}")
    row = await session.get(Template, key)
    if row is None:
        session.add(Template(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def list_templates(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Template))
    stored = {row.key: row.value for row in result.scalars().all()}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}
