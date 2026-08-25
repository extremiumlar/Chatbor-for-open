"""Rasm bo'yicha dublikat + mijoz lichkasidagi rasmga reaksiya.

Foydalanuvchi oqimni o'zgartirdi: tizim mijozga MATN yozmaydi (soya rejimi),
natija esa ikki joyda reaksiya bo'lib ko'rinadi — nazorat guruhida va admin
lichkasidagi rasmning ustida. Dublikat esa endi nomerdan tashqari RASM
bo'yicha ham aniqlanadi.
"""

import json

import pytest
from sqlalchemy import select

from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow
from core.models import Admin, Case, ScreenshotBatch, User
from core.enums import CaseStatus

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
OTHER_PHONE = "998907654321"


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


@pytest.fixture
def flow(session_factory):
    return ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)


async def _seed_case(session_factory, phone=PHONE, tg_id=TG_ID):
    async with session_factory() as session:
        if await session.get(Admin, ADMIN_ID) is None:
            session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
            await session.commit()
    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(
        ADMIN_ID, tg_id, "u", "Dilnoza", phone
    )
    return outcome.case


async def _close_case(session_factory, case_id):
    async with session_factory() as session:
        case = await session.get(Case, case_id)
        case.status = CaseStatus.REJECTED
        await session.commit()


# --------------------------------------------------------------------------- #
# Rasm bo'yicha dublikat
# --------------------------------------------------------------------------- #


async def test_same_image_under_a_different_phone_is_a_duplicate(
    session_factory, flow
):
    """Asosiy holat: mijoz nomerni o'zgartirib AYNAN o'sha skrinshotni
    qayta tashlaydi. Nomer boshqa, shuning uchun nomer bo'yicha tekshiruv
    buni o'tkazib yuborardi."""
    birinchi = await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1, media_ids=[5555])
    await _close_case(session_factory, birinchi.id)

    # Yangi nomer, lekin O'SHA rasm.
    await _seed_case(session_factory, phone=OTHER_PHONE)
    ikkinchi = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [20], 1, media_ids=[5555]
    )

    assert ikkinchi.is_duplicate is True, "o'sha rasm dublikat deb belgilanmadi"


async def test_different_images_under_a_different_phone_are_clean(
    session_factory, flow
):
    """Teskari tomon: boshqa nomer + boshqa rasm — bu normal yangi murojaat."""
    birinchi = await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1, media_ids=[5555])
    await _close_case(session_factory, birinchi.id)

    await _seed_case(session_factory, phone=OTHER_PHONE)
    ikkinchi = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [20], 1, media_ids=[7777]
    )

    assert ikkinchi.is_duplicate is False


async def test_same_image_in_the_same_case_is_not_a_duplicate(session_factory, flow):
    """§6.1a — admin o'sha case'ga rasmni qayta tashlashi NORMAL holat.
    Rasm bir xil bo'lsa ham dublikat emas."""
    await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1, media_ids=[5555])
    ikkinchi = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [20], 1, media_ids=[5555]
    )

    assert ikkinchi.is_duplicate is False


async def test_partial_image_overlap_counts_as_duplicate(session_factory, flow):
    """Partiyada 3 rasmdan bittasi eski bo'lsa ham — bu takror."""
    birinchi = await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 2, media_ids=[111, 222])
    await _close_case(session_factory, birinchi.id)

    await _seed_case(session_factory, phone=OTHER_PHONE)
    ikkinchi = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [20], 3, media_ids=[333, 222, 444]
    )

    assert ikkinchi.is_duplicate is True


async def test_media_ids_are_stored(session_factory, flow):
    """Keyingi qidiruvlar uchun media id'lar bazada saqlanishi kerak."""
    await _seed_case(session_factory)
    decision = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [10, 11], 2, media_ids=[901, 902]
    )

    async with session_factory() as session:
        batch = await session.get(ScreenshotBatch, decision.batch_id)
    assert json.loads(batch.media_ids) == [901, 902]


async def test_batches_without_media_ids_still_work(session_factory, flow):
    """Eski partiyalarda media id yo'q (o'shanda saqlanmagan) — ular
    qidiruvda qatnashmaydi va xato bermaydi."""
    birinchi = await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)  # media_ids yo'q
    await _close_case(session_factory, birinchi.id)

    await _seed_case(session_factory, phone=OTHER_PHONE)
    ikkinchi = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [20], 1, media_ids=[5555]
    )

    assert ikkinchi.is_duplicate is False


# --------------------------------------------------------------------------- #
# Statistika — dublikat ikki marta sanalmasin
# --------------------------------------------------------------------------- #


async def test_duplicate_batches_are_excluded_from_daily_counts(
    session_factory, flow
):
    """Kun oxiridagi hisobot to'g'ri chiqishi uchun: dublikat partiya
    `batches`/`images` ga EMAS, `duplicates` ga tushadi."""
    import datetime

    from core.logic.v2_stats import gather_v2_stats

    birinchi = await _seed_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 2, media_ids=[111, 222])
    await _close_case(session_factory, birinchi.id)

    await _seed_case(session_factory, phone=OTHER_PHONE)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 3, media_ids=[222])

    since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    async with session_factory() as session:
        report = await gather_v2_stats(session, since)

    qator = next(r for r in report.rows if r.admin_id == ADMIN_ID)
    assert qator.batches == 1, "dublikat partiya ham hisobga olindi"
    assert qator.images == 2, "dublikatdagi rasmlar ham sanaldi"
    assert qator.duplicates == 1
