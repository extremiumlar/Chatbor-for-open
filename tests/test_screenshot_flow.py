"""TZ v2 B-2 — ScreenshotFlow (rasm partiyasi) va BatchCollector testlari."""

import asyncio
import datetime

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.manual_case import ManualCaseManager
from core.logic.screenshots import ScreenshotFlow, format_phone_pretty, to_tashkent
from core.logic.settings_store import set_group_chat_id
from core.models import Admin, Case, JobKind, ScheduledJob, ScreenshotBatch
from teleton_service.batch_collector import BatchCollector

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
GROUP_ID = -100123456


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


@pytest.fixture
def make_flow(session_factory):
    def _make(alert_sink=None):
        return ScreenshotFlow(
            session_factory=session_factory, alert_sink=alert_sink or _noop_alert
        )

    return _make


async def _seed_admin_and_case(session_factory, tg_id=TG_ID, phone=PHONE):
    async with session_factory() as session:
        if await session.get(Admin, ADMIN_ID) is None:
            session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
            await session.commit()
    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, tg_id, "user1", "Dilnoza", phone)
    return outcome.case


async def _set_group(session_factory, chat_id=GROUP_ID):
    async with session_factory() as session:
        await set_group_chat_id(session, chat_id)


@pytest.mark.asyncio
async def test_batch_registered_status_and_jobs(session_factory, make_flow):
    case = await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10, 11], 2)

    assert decision.no_case is False
    assert decision.group_chat_id == GROUP_ID
    assert decision.customer_text  # SCREENSHOT_FOLLOWUP shabloni
    assert decision.is_duplicate is False

    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        assert db_case.status == CaseStatus.SCREENSHOTS_SENT

        jobs = (await session.execute(select(ScheduledJob))).scalars().all()
        by_kind = {}
        for j in jobs:
            by_kind.setdefault(j.kind, []).append(j)
        # Rasmsizlik eslatmasi yopilgan (done_at bor).
        assert all(j.done_at is not None for j in by_kind[JobKind.REMIND_NO_SCREENSHOT])
        # CHECK_DUE ochilgan — rasm vaqtidan +90daq.
        open_checks = [j for j in by_kind[JobKind.CHECK_DUE] if j.done_at is None]
        assert len(open_checks) == 1
        delta = open_checks[0].due_at - datetime.datetime.utcnow()
        assert datetime.timedelta(minutes=85) < delta < datetime.timedelta(minutes=95)


@pytest.mark.asyncio
async def test_caption_contains_required_fields(session_factory, make_flow):
    case = await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    assert f"#{case.short_code}" in decision.caption
    # T-13 — mijoz endi BOSILADIGAN havola (TZ §5.2), username yonida.
    assert f'<a href="tg://user?id={TG_ID}">Dilnoza</a> (@user1)' in decision.caption
    assert "+998 90 123 45 67" in decision.caption
    assert "Admin: Aziz" in decision.caption
    assert "Tekshiruv:" in decision.caption


# --------------------------------------------------------------------------- #
# T-15 — §5.3 shabloni mijozga BIR MARTA
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_t15_followup_template_is_sent_only_once_per_case(
    session_factory, make_flow
):
    """Jonli sinovda mijoz 3 partiyadan keyin bir xil matnni 3 marta oldi.
    Admin rasmni qayta tashlashi normal (§6.1a) — mijoz uchun bu spam."""
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    first = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    assert first.customer_text, "birinchi partiyada §5.3 matni bo'lishi kerak"
    # Relay matnni yuborgach shuni chaqiradi — shundan keyingina "yuborilgan"
    # deb hisoblanadi.
    await flow.mark_followup_sent(first.case_id)

    second = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)
    third = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [30], 1)

    assert second.customer_text is None
    assert third.customer_text is None


@pytest.mark.asyncio
async def test_t15_followup_retried_until_it_is_actually_sent(
    session_factory, make_flow
):
    """T-15 dagi teshik: shart "birinchi partiyami?" emas, "YUBORILGANMI?".

    Jonli sinovda birinchi partiya soya rejimida tashlangan (matn to'silgan),
    keyingilari esa "birinchi emas" deb jim qolgan — mijoz matnni HECH
    QACHON olmagan. Yuborilmagan matn keyingi partiyada qayta berilishi
    kerak.
    """
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    # 1-partiya: matn berildi, lekin yuborilmadi (soya rejimi / tarmoq xatosi)
    # — ya'ni `mark_followup_sent` CHAQIRILMAYDI.
    first = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    assert first.customer_text

    # 2-partiya: matn hali yetkazilmagani uchun QAYTA berilishi kerak.
    second = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)
    assert second.customer_text, "yuborilmagan matn qayta berilmadi"

    # Endi haqiqatan yuborildi deb belgilaymiz.
    await flow.mark_followup_sent(second.case_id)

    # 3-partiya: endi jim (spam bo'lmasin).
    third = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [30], 1)
    assert third.customer_text is None


@pytest.mark.asyncio
async def test_t15_mark_followup_sent_is_idempotent(session_factory, make_flow):
    """Ikki marta belgilansa birinchi vaqt saqlanib qolsin."""
    from core.models import Case

    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    await flow.mark_followup_sent(decision.case_id)
    async with session_factory() as session:
        birinchi = (await session.get(Case, decision.case_id)).followup_sent_at

    await flow.mark_followup_sent(decision.case_id)
    async with session_factory() as session:
        ikkinchi = (await session.get(Case, decision.case_id)).followup_sent_at

    assert birinchi == ikkinchi


@pytest.mark.asyncio
async def test_t15_new_case_gets_the_template_again(session_factory, make_flow):
    """Cheklov CASE ichida — yangi case yangi matn oladi (aks holda mijoz
    keyingi murojaatida umuman javob olmay qolardi)."""
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()

    first = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    await _open_second_case(session_factory)
    yangi_case_birinchi = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)

    assert first.customer_text
    assert yangi_case_birinchi.customer_text


# --------------------------------------------------------------------------- #
# T-13 — mijozga `tg://user?id=` havolasi
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_caption_links_customer_without_username(session_factory, make_flow):
    """Username'i yo'q mijozga ham o'tish imkoni bo'lishi kerak — avval
    caption'da bosilmaydigan `id:6644467393` turardi."""
    from core.models import User

    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == TG_ID))
        ).scalars().first()
        user.tg_username = None
        await session.commit()

    decision = await make_flow().register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    assert f'<a href="tg://user?id={TG_ID}">Dilnoza</a>' in decision.caption
    assert "(@" not in decision.caption  # username yo'q — qavs ham yo'q


@pytest.mark.asyncio
async def test_caption_escapes_html_in_user_supplied_text(session_factory, make_flow):
    """Caption HTML rejimida yuboriladi, shuning uchun mijoz/admin matni
    ekranlanishi shart — aks holda ismida `<` bo'lgan mijoz butun caption'ni
    buzardi (havola ham ishlamay qolardi)."""
    from core.models import User

    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == TG_ID))
        ).scalars().first()
        user.display_name = "Ali <b>&"
        user.tg_username = "a&b"
        await session.commit()

    decision = await make_flow().register_batch(ADMIN_ID, "A<z>iz", TG_ID, [10], 1)

    assert "Ali &lt;b&gt;&amp;" in decision.caption
    assert "(@a&amp;b)" in decision.caption
    assert "Admin: A&lt;z&gt;iz" in decision.caption
    # Faqat bizning havola tegi qolishi kerak, mijoz kiritgani emas.
    assert decision.caption.count("<a href=") == 1
    assert "<b>" not in decision.caption


# --------------------------------------------------------------------------- #
# Dublikat (§5.4) — T-10
#
# MUHIM farq: dublikat "shu nomer uchun BOSHQA case'da rasm tashlangan"
# degani. Bir case'ga qo'shimcha rasm tashlash §6.1a bo'yicha NORMAL holat.
# Avval ikkovi ham dublikat deb belgilanardi va jonli sinovda superadminga
# "ikki admin bitta mijoz ustida ishlayapti" degan noto'g'ri alert ketardi
# (aslida admin ham, case ham bitta edi).
# --------------------------------------------------------------------------- #


async def _open_second_case(session_factory, phone=PHONE):
    """O'sha mijoz + o'sha nomer uchun IKKINCHI case ochadi.

    To'g'ridan-to'g'ri bazaga yoziladi: `ManualCaseManager`ning o'z siyosati
    (ochiq case turganda yangisini ochmaslik) bu yerda tekshirilayotgan
    narsa emas — bizga faqat "ikki xil case" holati kerak.
    """
    from core.models import User

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == TG_ID))
        ).scalars().first()
        case = Case(user_id=user.id, phone=phone, status=CaseStatus.NUMBER_RECEIVED)
        session.add(case)
        await session.flush()
        case.short_code = f"C{case.id}"
        await session.commit()
        return case.id


@pytest.mark.asyncio
async def test_second_batch_on_the_same_case_is_not_a_duplicate(
    session_factory, make_flow
):
    """T-10 — §6.1a: admin o'sha case'ga ikkinchi marta rasm tashlasa, bu
    normal holat. Dublikat belgisi ham, alert ham bo'lmasligi kerak."""
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    flow = make_flow(alert_sink=capture)
    first = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    second = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)

    assert first.is_duplicate is False
    assert second.is_duplicate is False, "o'sha case'ga qo'shimcha rasm dublikat emas"
    assert "avval ham rasm tashlangan" not in second.caption
    assert not [a for a in alerts if "DUBLIKAT" in a], alerts

    async with session_factory() as session:
        batches = (await session.execute(select(ScreenshotBatch))).scalars().all()
    assert batches[1].is_duplicate is False
    assert batches[1].duplicate_of_batch_id is None


@pytest.mark.asyncio
async def test_batch_in_another_case_with_same_phone_is_a_duplicate(
    session_factory, make_flow
):
    """T-10 — haqiqiy dublikat: o'sha nomer BOSHQA case'da qayta paydo
    bo'ldi. Bu holatda belgi ham, alert ham qolishi kerak."""
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    flow = make_flow(alert_sink=capture)
    first = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    await _open_second_case(session_factory)
    second = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert "avval ham rasm tashlangan" in second.caption
    assert any("DUBLIKAT" in a for a in alerts), alerts

    async with session_factory() as session:
        batches = (await session.execute(select(ScreenshotBatch))).scalars().all()
    assert batches[1].is_duplicate is True
    assert batches[1].duplicate_of_batch_id == batches[0].id


@pytest.mark.asyncio
async def test_duplicate_alert_names_the_real_reason(session_factory, make_flow):
    """T-10 — sabab ikki xil va ular teng emas: o'sha adminning takrori
    yoki ikki adminning to'qnashuvi. Avval ikkovi ham "ikki admin
    ishlayapti" deb xabar qilinardi."""
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    flow = make_flow(alert_sink=capture)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    # (a) O'SHA admin, boshqa case.
    await _open_second_case(session_factory)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)
    assert "O'SHA admin" in alerts[-1]
    assert "IKKI ADMIN" not in alerts[-1]

    # (b) BOSHQA admin, yana boshqa case.
    async with session_factory() as session:
        session.add(Admin(id=2, tg_user_id=902, name="Bekzod"))
        await session.commit()
    await _open_second_case(session_factory)
    await flow.register_batch(2, "Bekzod", TG_ID, [30], 1)

    assert "IKKI ADMIN" in alerts[-1]
    assert "Aziz" in alerts[-1] and "Bekzod" in alerts[-1]


@pytest.mark.asyncio
async def test_no_open_case_returns_no_case(session_factory, make_flow):
    flow = make_flow()
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    assert decision.no_case is True

    async with session_factory() as session:
        batches = (await session.execute(select(ScreenshotBatch))).scalars().all()
    assert batches == []


@pytest.mark.asyncio
async def test_group_not_configured_alerts_but_stores(session_factory, make_flow):
    await _seed_admin_and_case(session_factory)
    alerts: list[str] = []

    async def capture(message: str, important: bool = True) -> None:
        alerts.append(message)

    flow = make_flow(alert_sink=capture)
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    assert decision.group_chat_id is None
    assert any("guruhi sozlanmagan" in a for a in alerts)
    async with session_factory() as session:
        batches = (await session.execute(select(ScreenshotBatch))).scalars().all()
    assert len(batches) == 1  # bazaga baribir yozildi


@pytest.mark.asyncio
async def test_record_group_post(session_factory, make_flow):
    await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)

    await flow.record_group_post(decision.batch_id, GROUP_ID, 555)

    async with session_factory() as session:
        batch = await session.get(ScreenshotBatch, decision.batch_id)
    assert batch.group_chat_id == GROUP_ID
    assert batch.group_message_id == 555


@pytest.mark.asyncio
async def test_second_batch_reschedules_check_due(session_factory, make_flow):
    case = await _seed_admin_and_case(session_factory)
    await _set_group(session_factory)
    flow = make_flow()
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [10], 1)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [20], 1)

    async with session_factory() as session:
        open_checks = (
            (
                await session.execute(
                    select(ScheduledJob).where(
                        ScheduledJob.case_id == case.id,
                        ScheduledJob.kind == JobKind.CHECK_DUE,
                        ScheduledJob.done_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    # Taymer QAYTA rejalangan — faqat bitta ochiq CHECK_DUE qoladi (§6.1 a).
    assert len(open_checks) == 1


def test_format_phone_pretty():
    assert format_phone_pretty("998901234567") == "+998 90 123 45 67"
    assert format_phone_pretty("acme") == "acme"


def test_to_tashkent_offset():
    utc = datetime.datetime(2026, 8, 11, 9, 32)
    assert to_tashkent(utc).hour == 14  # UTC+5


# --------------------------------------------------------------------------- #
# BatchCollector
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_collector_solo_window_groups_messages():
    batches: list[tuple[int, list]] = []

    async def on_ready(chat_id, messages):
        batches.append((chat_id, messages))

    collector = BatchCollector(on_ready, window_seconds=0.05)
    collector.add(100, "rasm1")
    collector.add(100, "rasm2")
    await asyncio.sleep(0.1)

    assert batches == [(100, ["rasm1", "rasm2"])]


@pytest.mark.asyncio
async def test_collector_separate_chats_separate_batches():
    batches: list[tuple[int, list]] = []

    async def on_ready(chat_id, messages):
        batches.append((chat_id, messages))

    collector = BatchCollector(on_ready, window_seconds=0.05)
    collector.add(100, "a")
    collector.add(200, "b")
    await asyncio.sleep(0.1)

    assert sorted(batches) == [(100, ["a"]), (200, ["b"])]


@pytest.mark.asyncio
async def test_collector_album_debounce():
    batches: list[tuple[int, list]] = []

    async def on_ready(chat_id, messages):
        batches.append((chat_id, messages))

    collector = BatchCollector(on_ready, window_seconds=99)  # oyna ishlatilmaydi
    collector.add(100, "a1", grouped_id=777)
    collector.add(100, "a2", grouped_id=777)
    # Albom debounce ~2s — drain bilan darhol yopamiz.
    await collector.drain()

    assert batches == [(100, ["a1", "a2"])]


@pytest.mark.asyncio
async def test_collector_window_not_extended_by_new_messages():
    """Yakka-rasm oynasi birinchi rasmdan boshlab QAT'IY — keyingi rasmlar
    uni cho'zmaydi."""
    batches: list[list] = []

    async def on_ready(chat_id, messages):
        batches.append(messages)

    collector = BatchCollector(on_ready, window_seconds=0.08)
    collector.add(100, "r1")
    await asyncio.sleep(0.05)
    collector.add(100, "r2")  # oyna ichida — qo'shiladi
    await asyncio.sleep(0.06)  # jami 0.11 > 0.08 — oyna yopildi
    collector.add(100, "r3")  # yangi partiya boshlanadi
    await asyncio.sleep(0.1)

    assert batches == [["r1", "r2"], ["r3"]]
