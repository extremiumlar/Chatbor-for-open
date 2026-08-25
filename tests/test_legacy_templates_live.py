"""v1 merosidagi shablonlar v2 oqimida ishlatilishi (foydalanuvchi qaroriga ko'ra).

TZ v2 dastlab "tizim jim, admin o'zi gaplashadi" tamoyiliga qurilgan edi va
bu uchta holatda mijozga hech narsa yozilmasdi. Foydalanuvchi ularni
yoqishni so'radi — matnlari allaqachon yozib qo'yilgan edi, faqat hech
qachon yuborilmasdi.

Yoqilganlari:
    DUPLICATE_ACTIVE       — ochiq murojaat turib BOSHQA nomer kelsa
    DUPLICATE_COUPON       — case'da allaqachon BOSHQA kupon bo'lsa
    IMAGE_INSTEAD_OF_TEXT  — mijoz nomerni rasm/ovoz bilan yuborsa
"""

import datetime

import pytest

from core.enums import CaseStatus
from core.logic.manual_case import ManualCaseManager
from core.logic.templates import ensure_templates_seeded, set_template
from core.models import Admin, Case

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
OTHER_PHONE = "998907654321"


@pytest.fixture
def manager(session_factory):
    return ManualCaseManager(session_factory=session_factory)


async def _seed(session_factory):
    async with session_factory() as session:
        if await session.get(Admin, ADMIN_ID) is None:
            session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await ensure_templates_seeded(session)
        await session.commit()


# --------------------------------------------------------------------------- #
# DUPLICATE_ACTIVE
# --------------------------------------------------------------------------- #


async def test_second_different_phone_now_opens_its_own_case(session_factory, manager):
    """DUPLICATE_ACTIVE endi YUBORILMAYDI — oqim o'zgardi.

    Bir muddat u yoqilgan edi ("oldingi so'rovingiz hali tugamagan"), lekin
    keyin ikkinchi nomer rad etilmaydigan bo'ldi: u o'z case'ini oladi va
    navbatga tushadi. Bunday holatda o'sha matn YOLG'ON bo'lardi.
    `test_multi_number_routing.py` ga qarang.
    """
    await _seed(session_factory)

    birinchi = await manager.handle_phone_detected(
        ADMIN_ID, TG_ID, None, None, PHONE
    )
    ikkinchi = await manager.handle_phone_detected(
        ADMIN_ID, TG_ID, None, None, OTHER_PHONE
    )

    assert ikkinchi.customer_text is None
    assert ikkinchi.case.id != birinchi.case.id, "ikkinchi nomer o'z case'ini olmadi"
    assert ikkinchi.case.phone == OTHER_PHONE


async def test_same_phone_again_stays_silent(session_factory, manager):
    """O'SHA nomer qayta yozilsa — bu oddiy suhbat, javob kerak emas."""
    await _seed(session_factory)

    await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    assert outcome.customer_text is None


# --------------------------------------------------------------------------- #
# DUPLICATE_COUPON
# --------------------------------------------------------------------------- #


async def test_second_different_coupon_tells_the_customer(session_factory, manager):
    await _seed(session_factory)
    async with session_factory() as session:
        await set_template(session, "DUPLICATE_COUPON", "Bu eski kod")

    await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    assert await manager.handle_coupon_detected(TG_ID, "111111") is None

    javob = await manager.handle_coupon_detected(TG_ID, "222222")

    assert javob == "Bu eski kod"


async def test_resending_the_same_coupon_stays_silent(session_factory, manager):
    """Aynan o'sha kuponni takror yuborish — "bu eski kod" deyish chalkash
    bo'lardi, chunki kod eski emas, o'shaning o'zi."""
    await _seed(session_factory)

    await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    await manager.handle_coupon_detected(TG_ID, "111111")

    assert await manager.handle_coupon_detected(TG_ID, "111111") is None


async def test_first_coupon_is_still_saved(session_factory, manager):
    """Regressiya: birinchi kupon avvalgidek bazaga yozilishi kerak."""
    await _seed(session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)

    await manager.handle_coupon_detected(TG_ID, "123456")

    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
    assert case.coupon == "123456"


# --------------------------------------------------------------------------- #
# IMAGE_INSTEAD_OF_TEXT — spam himoyasi
# --------------------------------------------------------------------------- #


def test_image_hint_cooldown_blocks_bursts():
    """Albom (5–10 rasm) bitta eslatma olishi kerak, har rasmga emas."""
    import teleton_service.manual_relay as relay

    relay._image_hint_sent.clear()
    now = datetime.datetime(2026, 8, 23, 12, 0, 0)

    assert relay._image_hint_due(1, 500, now) is True
    # Albomning qolgan rasmlari — bir necha soniya ichida.
    for sekund in (1, 2, 3, 8):
        assert relay._image_hint_due(1, 500, now + datetime.timedelta(seconds=sekund)) is False

    # Sovutish oralig'i o'tgach — yana mumkin.
    keyin = now + datetime.timedelta(minutes=relay._IMAGE_HINT_COOLDOWN_MINUTES, seconds=1)
    assert relay._image_hint_due(1, 500, keyin) is True


def test_image_hint_is_per_conversation():
    """Bir mijozga yuborilgani boshqasini to'smasligi kerak."""
    import teleton_service.manual_relay as relay

    relay._image_hint_sent.clear()
    now = datetime.datetime(2026, 8, 23, 12, 0, 0)

    assert relay._image_hint_due(1, 500, now) is True
    assert relay._image_hint_due(1, 600, now) is True   # boshqa mijoz
    assert relay._image_hint_due(2, 500, now) is True   # boshqa admin


async def test_image_hint_only_when_no_open_case(session_factory, manager, monkeypatch):
    """Case ochiq bo'lsa mijoz nomerini allaqachon yozgan — rasmi oddiy
    suhbat, unga "nomerni matn qilib yuboring" deyish noto'g'ri."""
    import teleton_service.manual_relay as relay

    monkeypatch.setattr(relay, "get_session", session_factory)
    await _seed(session_factory)

    # Hali case yo'q — eslatma o'rinli.
    assert await relay._has_open_case(TG_ID) is False

    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, None, None, PHONE)
    assert await relay._has_open_case(TG_ID) is True

    # Case yopilgach yana o'rinli bo'ladi.
    async with session_factory() as session:
        case = await session.get(Case, outcome.case.id)
        case.status = CaseStatus.REJECTED
        await session.commit()
    assert await relay._has_open_case(TG_ID) is False


async def test_media_detection():
    """Faqat media bo'lgan xabarga javob beriladi — bo'sh xizmat
    xabarlariga emas."""
    import teleton_service.manual_relay as relay

    class _Msg:
        photo = None
        document = None
        voice = None
        video = None
        contact = None
        audio = None

    class _Event:
        def __init__(self, msg):
            self.message = msg

    bosh = _Msg()
    assert await relay._has_media(_Event(bosh)) is False

    rasmli = _Msg()
    rasmli.photo = object()
    assert await relay._has_media(_Event(rasmli)) is True

    assert await relay._has_media(_Event(None)) is False
