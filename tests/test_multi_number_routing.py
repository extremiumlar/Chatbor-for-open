"""Mijoz 2-3 nomer yuborganda rasm TO'G'RI nomerga tushishi.

Foydalanuvchi shikoyati: "kopincha 2-3 ta nomer tashaydiganlarda adashadi
(chunki 2-3 ta rasm tashaladi)". Takrorlandi va tasdiqlandi:

  * ochiq case turganda ikkinchi nomer YANGI case ochmasdi — u butunlay
    yo'qolardi (tekshiruv ham, statistika ham yo'q);
  * admin o'sha nomer uchun rasm tashlaganda partiya BIRINCHI nomer bilan
    belgilanardi va guruhga xato caption tushardi.

Yechim (foydalanuvchi tanlovi): har nomer o'z case'ini oladi; admin
nomerli xabarga REPLY qilib rasm tashlaydi; reply bo'lmasa tizim taxmin
qilmaydi — darhol ogohlantiradi.
"""

import pytest

from core.enums import CaseStatus
from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import set_group_chat_id
from core.models import Admin, Case
from sqlalchemy import select

ADMIN_ID = 1
TG_ID = 555
A = "998901111111"
B = "998902222222"
C = "998903333333"

# Mijozning nomer yozgan xabarlari id'lari.
MSG_A, MSG_B, MSG_C = 101, 102, 103


@pytest.fixture
def alerts():
    yozilgan: list[str] = []

    async def sink(message: str, important: bool = True) -> None:
        yozilgan.append(message)

    sink.yozilgan = yozilgan
    return sink


@pytest.fixture
async def env(session_factory, alerts):
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await set_group_chat_id(session, -100555)
        await session.commit()
    manager = ManualCaseManager(session_factory=session_factory, alert_sink=alerts)
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=alerts)
    return manager, flow, alerts


async def _yubor(manager, phone, msg_id):
    return await manager.handle_phone_detected(
        ADMIN_ID, TG_ID, "u", "Mijoz", phone, message_id=msg_id
    )


# --------------------------------------------------------------------------- #
# Har nomer o'z case'ini oladi
# --------------------------------------------------------------------------- #


async def test_each_number_gets_its_own_case(session_factory, env):
    """Avval 3 nomer bitta case'ga tushib, 2 tasi yo'qolardi."""
    manager, _, _ = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    await _yubor(manager, C, MSG_C)

    async with session_factory() as session:
        cases = (await session.execute(select(Case).order_by(Case.id))).scalars().all()

    assert [c.phone for c in cases] == [A, B, C], "ikkinchi/uchinchi nomer yo'qoldi"
    assert all(c.status == CaseStatus.NUMBER_RECEIVED for c in cases)
    assert [c.origin_message_id for c in cases] == [MSG_A, MSG_B, MSG_C]


async def test_same_number_repeated_does_not_open_a_second_case(session_factory, env):
    """O'SHA nomer qayta yozilsa — bu oddiy suhbat, yangi case emas."""
    manager, _, _ = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, A, MSG_A + 50)

    async with session_factory() as session:
        cases = (await session.execute(select(Case))).scalars().all()
    assert len(cases) == 1


# --------------------------------------------------------------------------- #
# Reply — aniq bog'lash
# --------------------------------------------------------------------------- #


async def test_reply_routes_the_batch_to_the_right_number(session_factory, env):
    """Asosiy holat: uch nomer ochiq, admin ikkinchisiga reply qilib rasm
    tashlaydi — partiya AYNAN o'sha nomerga tushishi kerak."""
    manager, flow, _ = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    await _yubor(manager, C, MSG_C)

    decision = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=MSG_B
    )

    assert f"📱 +998 90 222 22 22" in decision.caption
    async with session_factory() as session:
        case = await session.get(Case, decision.case_id)
    assert case.phone == B


@pytest.mark.parametrize("msg_id,kutilgan", [(MSG_A, A), (MSG_B, B), (MSG_C, C)])
async def test_reply_works_for_every_number(session_factory, env, msg_id, kutilgan):
    manager, flow, _ = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    await _yubor(manager, C, MSG_C)

    decision = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=msg_id
    )

    async with session_factory() as session:
        case = await session.get(Case, decision.case_id)
    assert case.phone == kutilgan


async def test_reply_does_not_warn(session_factory, env):
    """Reply bor — noaniqlik yo'q, ogohlantirish ham kerak emas."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    alerts.yozilgan.clear()

    await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=MSG_B
    )

    assert not [a for a in alerts.yozilgan if "REPLY'siz" in a]


# --------------------------------------------------------------------------- #
# Reply yo'q — ogohlantirish
# --------------------------------------------------------------------------- #


async def test_no_reply_with_several_numbers_warns_immediately(session_factory, env):
    """Foydalanuvchi talabi: reply qilmasa — darhol ogohlantirish."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    alerts.yozilgan.clear()

    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [900], 1)

    ogoh = [a for a in alerts.yozilgan if "REPLY'siz" in a]
    assert ogoh, "ikki nomer ochiq, reply yo'q — ogohlantirish kelmadi"
    # Ogohlantirish foydali bo'lishi kerak: nomerlar va nima qilish.
    assert "+998 90 111 11 11" in ogoh[0]
    assert "+998 90 222 22 22" in ogoh[0]
    assert "reply" in ogoh[0].lower()


async def test_single_open_number_needs_no_reply(session_factory, env):
    """Bitta nomer bo'lsa noaniqlik yo'q — ogohlantirish bezovta qilmasin."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)
    alerts.yozilgan.clear()

    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [900], 1)

    assert not [a for a in alerts.yozilgan if "REPLY'siz" in a]
    async with session_factory() as session:
        case = await session.get(Case, decision.case_id)
    assert case.phone == A


async def test_ambiguous_batch_goes_to_the_oldest_number_awaiting_images(
    session_factory, env
):
    """Taxmin qilmaslik mumkin emas — rasm biror joyga yozilishi kerak.
    Tanlov: rasm KUTAYOTGAN eng eski nomer (admin odatda kelgan tartibda
    ovoz beradi). Bu tanlov ogohlantirishda ochiq aytiladi."""
    manager, flow, _ = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)

    # A ga rasm allaqachon tashlangan -> keyingisi B ga tushishi kerak.
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=MSG_A)
    ikkinchi = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [901], 1)

    async with session_factory() as session:
        case = await session.get(Case, ikkinchi.case_id)
    assert case.phone == B


async def test_reply_to_an_unrelated_message_falls_back_to_warning(
    session_factory, env
):
    """Admin eski rasmga reply qilsa — bu nomer ko'rsatmasi emas."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)
    await _yubor(manager, B, MSG_B)
    alerts.yozilgan.clear()

    await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=999999
    )

    assert [a for a in alerts.yozilgan if "ekanini bilmaydi" in a]


async def test_reply_resolves_to_a_closed_case_too(session_factory, env):
    """Foydalanuvchi talabi: reply qilingan bo'lsa, case OCHIQMI YO'QMI
    farqi yo'q — o'sha reply qilingan nomerga rasm tushishi kerak. Case
    allaqachon FAILED bo'lsa ham (masalan qayta tekshiruv uchun dalil
    tashlanayotgan bo'lsa), reply orqali to'g'ridan-to'g'ri topilishi
    kerak — hech qanday ochiq case yo'qligiga qaramay."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)
    async with session_factory() as session:
        case = (await session.execute(select(Case).where(Case.phone == A))).scalars().first()
        case.status = CaseStatus.FAILED
        await session.commit()
    alerts.yozilgan.clear()

    decision = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=MSG_A
    )

    assert not decision.no_case, "yopiq case'ga reply qilinganda ham topilishi kerak edi"
    async with session_factory() as session:
        result_case = await session.get(Case, decision.case_id)
    assert result_case.phone == A
    assert not [a for a in alerts.yozilgan if "ekanini bilmaydi" in a]


async def test_mismatched_reply_warns_even_with_a_single_open_case(
    session_factory, env
):
    """Jonli xato: mijozda FAQAT bitta (eski, chalkash) ochiq case qolgan
    bo'lsa, admin YANGI xabarga reply qilib rasm tashlasa ham, reply hech
    kimga mos kelmasa — tizim buni AVVAL jimgina yagona case'ga yozib
    qo'yardi (ogohlantirmasdan). "Reply qilsam ham qilmasam ham bitta
    (eski) nomer guruhga tushadi" shikoyati aynan shundan edi."""
    manager, flow, alerts = env
    await _yubor(manager, A, MSG_A)  # yagona ochiq case
    alerts.yozilgan.clear()

    decision = await flow.register_batch(
        ADMIN_ID, "Aziz", TG_ID, [900], 1, reply_to_msg_id=999999
    )

    assert [a for a in alerts.yozilgan if "ekanini bilmaydi" in a], (
        "reply mos kelmadi, lekin ogohlantirilmadi"
    )
    async with session_factory() as session:
        case = await session.get(Case, decision.case_id)
    assert case.phone == A  # yagona ochiq case — baribir shunga tushadi, lekin OGOHLANTIRIB
