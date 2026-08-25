"""TZ v2 B-4 — ResultDistributor (natija tarqatish, aralash rejim) testlari."""

import datetime

import pytest
from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.check_engine import CheckEngine
from core.logic.check_patterns import CheckCategory, add_pattern
from core.logic.job_poller import JobPoller
from core.logic.manual_case import ManualCaseManager
from core.logic.result_flow import ResultDistributor
from core.logic.screenshots import ScreenshotFlow
from core.logic.settings_store import (
    set_checker_account,
    set_group_chat_id,
    set_shadow_mode,
)
from core.models import (
    Admin,
    BatchOutcome,
    Case,
    CheckRequest,
    CheckTrigger,
    JobKind,
    NotifiedBy,
    ScheduledJob,
    ScreenshotBatch,
)

ADMIN_ID = 1
TG_ID = 111
PHONE = "998901234567"
GROUP_ID = -100555
GROUP_MSG_ID = 777


async def _noop_alert(message: str, important: bool = True) -> None:
    pass


class FakeSender:
    def __init__(self):
        self.sent = []
        self._next_id = 1000

    async def __call__(self, admin_id, text):
        self.sent.append((admin_id, text))
        self._next_id += 1
        return self._next_id


class Callbacks:
    def __init__(self, react_ok=True, send_ok=True):
        self.react_ok = react_ok
        self.send_ok = send_ok
        self.reactions: list[tuple] = []
        self.customer: list[tuple] = []
        self.confirmations: list[tuple] = []

    async def set_reaction(self, admin_id, chat_id, msg_id, emoji) -> bool:
        self.reactions.append((admin_id, chat_id, msg_id, emoji))
        return self.react_ok

    async def send_customer(self, admin_id, tg_user_id, text) -> bool:
        self.customer.append((admin_id, tg_user_id, text))
        return self.send_ok

    async def failed_confirmation(self, message, request_id) -> None:
        self.confirmations.append((message, request_id))


async def _setup(session_factory, callbacks=None, alerts=None, shadow=False):
    """Admin + shablonlar + tekshiruvchi + rasm-guruh posti bilan tayyor case."""
    async with session_factory() as session:
        session.add(Admin(id=ADMIN_ID, tg_user_id=901, name="Aziz"))
        await session.commit()
        await add_pattern(session, CheckCategory.CHECK_PASSED, "bor")
        await add_pattern(session, CheckCategory.CHECK_FAILED, "yo'q")
        await add_pattern(session, CheckCategory.CHECK_ERROR, "xato")
        await set_checker_account(session, "checker")
        await set_group_chat_id(session, GROUP_ID)
        await set_shadow_mode(session, shadow)

    manager = ManualCaseManager(session_factory=session_factory)
    outcome = await manager.handle_phone_detected(ADMIN_ID, TG_ID, "u", "Dilnoza", PHONE)

    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [1, 2], 2)
    await flow.record_group_post(decision.batch_id, GROUP_ID, GROUP_MSG_ID)

    cb = callbacks or Callbacks()
    alert_list = alerts if alerts is not None else []

    async def capture_alert(message: str, important: bool = True) -> None:
        alert_list.append(message)

    distributor = ResultDistributor(
        session_factory=session_factory,
        alert_sink=capture_alert,
        set_reaction=cb.set_reaction,
        send_customer=cb.send_customer,
        failed_confirmation=cb.failed_confirmation,
    )
    engine = CheckEngine(
        session_factory=session_factory,
        alert_sink=capture_alert,
        send_to_checker=FakeSender(),
        result_hook=distributor.on_result,
        stalled_hook=distributor.on_stalled,
    )
    return outcome.case, engine, distributor, cb


async def _send_request(engine, case_id):
    await engine.request_check(case_id, CheckTrigger.AUTO)
    await engine.drip_tick()


def _group_reactions(cb):
    """Faqat NAZORAT GURUHIDAGI reaksiyalar.

    Natija endi ikki joyga qo'yiladi — guruhga va mijoz lichkasidagi
    rasmga. Guruh mantig'ini tekshiruvchi testlar lichkanikini
    hisobga olmasligi kerak.
    """
    return [r for r in cb.reactions if r[1] == GROUP_ID]


def _dm_reactions(cb):
    """Mijoz lichkasidagi rasmga qo'yilgan reaksiyalar."""
    return [r for r in cb.reactions if r[1] == TG_ID]


@pytest.mark.asyncio
async def test_passed_auto_notifies_customer_and_reacts(session_factory):
    case, engine, _, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)

    await engine.handle_checker_reply(ADMIN_ID, "bor")

    assert _group_reactions(cb) == [(ADMIN_ID, GROUP_ID, GROUP_MSG_ID, "👍")]
    # Mijoz lichkasidagi BIRINCHI rasmga ham o'sha natija qo'yiladi —
    # admin lichkada ham "o'tdimi?" degan savolga javob ko'radi.
    assert _dm_reactions(cb) == [(ADMIN_ID, TG_ID, 1, "👍")]
    assert len(cb.customer) == 1
    assert cb.customer[0][1] == TG_ID
    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert req.notified_by == NotifiedBy.AUTO
    assert req.customer_notified_at is not None
    assert batch.outcome == BatchOutcome.PASSED


@pytest.mark.asyncio
async def test_passed_shadow_mode_no_customer_message(session_factory):
    alerts: list[str] = []
    case, engine, _, cb = await _setup(session_factory, alerts=alerts, shadow=True)
    await _send_request(engine, case.id)

    await engine.handle_checker_reply(ADMIN_ID, "bor")

    assert cb.customer == []  # soya — mijozga yozilmaydi
    assert cb.reactions[0][3] == "👍"  # reaksiya baribir qo'yiladi
    assert any("soya" in a for a in alerts)


@pytest.mark.asyncio
async def test_failed_asks_admin_confirmation(session_factory):
    case, engine, _, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)

    await engine.handle_checker_reply(ADMIN_ID, "yo'q")

    assert cb.customer == []  # tasdiqlashsiz yuborilmaydi
    assert len(cb.confirmations) == 1
    assert cb.reactions[0][3] == "👎"
    async with session_factory() as session:
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert batch.outcome == BatchOutcome.FAILED


@pytest.mark.asyncio
async def test_send_failed_now_notifies_once(session_factory):
    case, engine, distributor, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)
    await engine.handle_checker_reply(ADMIN_ID, "yo'q")
    request_id = cb.confirmations[0][1]

    await distributor.send_failed_now(request_id)
    await distributor.send_failed_now(request_id)  # takror bosish — no-op

    assert len(cb.customer) == 1
    async with session_factory() as session:
        req = await session.get(CheckRequest, request_id)
    assert req.notified_by == NotifiedBy.ADMIN


@pytest.mark.asyncio
async def test_unrecognized_reacts_warning_no_customer(session_factory):
    case, engine, _, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)

    await engine.handle_checker_reply(ADMIN_ID, "xato yubordingiz")

    assert cb.customer == []
    assert cb.confirmations == []
    assert cb.reactions[0][3] == "⚠️"
    async with session_factory() as session:
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert batch.outcome == BatchOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_stalled_reacts_hourglass(session_factory):
    case, engine, _, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
    await engine.handle_stalled(req.id)

    assert cb.reactions[-1][3] == "⏳"
    async with session_factory() as session:
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert batch.outcome == BatchOutcome.STALLED


@pytest.mark.asyncio
async def test_late_reply_auto_corrects_and_tells_admin(session_factory):
    """§6.5 (foydalanuvchi qarori 1b): admin O'TMADI deb yopgan, tekshiruvchi
    keyin "bor" dedi — natija avtomatik to'g'irlanadi, mijozga TIZIM yozmaydi,
    adminga "uzr so'rab o'zingiz yozing" xabari boradi."""
    alerts: list[str] = []
    case, engine, _, cb = await _setup(session_factory, alerts=alerts, shadow=False)
    await _send_request(engine, case.id)

    # Admin so'rov ochiqligida case'ni qo'lda FAILED deb yopdi.
    async with session_factory() as session:
        db_case = await session.get(Case, case.id)
        db_case.status = CaseStatus.FAILED
        await session.commit()

    # 5 soatdan keyin tekshiruvchi javob berdi: aslida o'tgan.
    await engine.handle_checker_reply(ADMIN_ID, "bor")

    async with session_factory() as session:
        req = (await session.execute(select(CheckRequest))).scalars().first()
        db_case = await session.get(Case, case.id)
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert req.late_corrected is True
    assert db_case.status == CaseStatus.PASSED  # avtomatik to'g'irlandi
    assert batch.outcome == BatchOutcome.PASSED
    assert cb.reactions[-1][3] == "👍"  # 👎 -> 👍
    assert cb.customer == []  # uzrni admin o'zi yozadi
    assert any("uzr" in a.lower() for a in alerts)


@pytest.mark.asyncio
async def test_reaction_failure_alerts_but_keeps_result(session_factory):
    alerts: list[str] = []
    cb = Callbacks(react_ok=False)
    case, engine, _, cb = await _setup(
        session_factory, callbacks=cb, alerts=alerts, shadow=True
    )
    await _send_request(engine, case.id)

    await engine.handle_checker_reply(ADMIN_ID, "bor")

    assert any("reaksiya qo'yib bo'lmadi" in a for a in alerts)
    async with session_factory() as session:
        batch = (await session.execute(select(ScreenshotBatch))).scalars().first()
    assert batch.outcome == BatchOutcome.PASSED  # natija bazada saqlangan


@pytest.mark.asyncio
async def test_notify_failed_job_via_poller(session_factory):
    """Adminbot tugmasi NOTIFY_FAILED job yozadi — poller mijozga yuboradi."""
    case, engine, distributor, cb = await _setup(session_factory, shadow=False)
    await _send_request(engine, case.id)
    await engine.handle_checker_reply(ADMIN_ID, "yo'q")
    request_id = cb.confirmations[0][1]

    # Adminbot tomonida yaratiladigan job (bir xil kod yo'li).
    async with session_factory() as session:
        session.add(
            ScheduledJob(
                kind=JobKind.NOTIFY_FAILED,
                case_id=case.id,
                due_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=1),
                payload=f'{{"request_id": {request_id}}}',
            )
        )
        await session.commit()

    poller = JobPoller(
        session_factory, engine, _noop_alert, poll_seconds=999, distributor=distributor
    )
    await poller.tick()

    assert len(cb.customer) == 1
    async with session_factory() as session:
        req = await session.get(CheckRequest, request_id)
    assert req.notified_by == NotifiedBy.ADMIN


# --------------------------------------------------------------------------- #
# T-6 — case'ning BARCHA partiyalari natija olsin
#
# §6.1a bo'yicha admin rasmni qayta tashlashi NORMAL holat, shuning uchun
# bitta case'da bir necha partiya bo'lishi muntazam. Avval faqat OXIRGISI
# belgilanardi: guruhda belgisiz, abadiy PENDING postlar qolib ketardi va
# §8.2 statistikasi buzilardi (jonli sinov C7: 3 partiyadan faqat 1 tasi 👍).
# --------------------------------------------------------------------------- #


@pytest.fixture
def no_pause(monkeypatch):
    """Partiyalar orasidagi §4.5 pauzasini testda o'tkazib yuboramiz."""
    import core.logic.result_flow as rf

    async def instant(_seconds):
        return None

    monkeypatch.setattr(rf.asyncio, "sleep", instant)


@pytest.mark.asyncio
async def test_t6_all_batches_of_a_case_get_outcome_and_reaction(
    session_factory, no_pause
):
    case, engine, _, cb = await _setup(session_factory, shadow=False)

    # Yana ikkita partiya (admin rasmni qayta tashladi) — har biri guruhda.
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    for msg_id in (GROUP_MSG_ID + 6, GROUP_MSG_ID + 12):
        decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [msg_id], 1)
        await flow.record_group_post(decision.batch_id, GROUP_ID, msg_id)

    await _send_request(engine, case.id)
    await engine.handle_checker_reply(ADMIN_ID, "bor")

    async with session_factory() as session:
        batches = (
            await session.execute(select(ScreenshotBatch).order_by(ScreenshotBatch.id))
        ).scalars().all()

    assert len(batches) == 3
    assert all(b.outcome == BatchOutcome.PASSED for b in batches), (
        "faqat oxirgi partiya belgilandi — qolganlari PENDING qoldi"
    )
    reacted = {r[2] for r in _group_reactions(cb)}
    assert reacted == {GROUP_MSG_ID, GROUP_MSG_ID + 6, GROUP_MSG_ID + 12}


@pytest.mark.asyncio
async def test_t6_manually_marked_batch_is_left_alone(session_factory, no_pause):
    """§7.3 — odam qarori avtomatikadan ustun."""
    from core.models import OutcomeSource

    case, engine, _, cb = await _setup(session_factory, shadow=False)

    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    decision = await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [99], 1)
    await flow.record_group_post(decision.batch_id, GROUP_ID, 999)

    # Ikkinchi partiyani admin qo'lda 👎 qilib qo'ygan.
    async with session_factory() as session:
        manual = await session.get(ScreenshotBatch, decision.batch_id)
        manual.outcome = BatchOutcome.FAILED
        manual.outcome_source = OutcomeSource.MANUAL
        await session.commit()

    await _send_request(engine, case.id)
    await engine.handle_checker_reply(ADMIN_ID, "bor")

    async with session_factory() as session:
        manual = await session.get(ScreenshotBatch, decision.batch_id)

    assert manual.outcome == BatchOutcome.FAILED, "qo'lda qo'yilgan natija bosib ketildi"
    assert manual.outcome_source == OutcomeSource.MANUAL
    assert 999 not in {r[2] for r in cb.reactions}


@pytest.mark.asyncio
async def test_t6_batch_without_group_post_is_skipped(session_factory, no_pause):
    case, engine, _, cb = await _setup(session_factory, shadow=False)

    # Guruhga tushmagan partiya (record_group_post chaqirilmagan).
    flow = ScreenshotFlow(session_factory=session_factory, alert_sink=_noop_alert)
    await flow.register_batch(ADMIN_ID, "Aziz", TG_ID, [55], 1)

    await _send_request(engine, case.id)
    await engine.handle_checker_reply(ADMIN_ID, "bor")

    async with session_factory() as session:
        batches = (
            await session.execute(select(ScreenshotBatch).order_by(ScreenshotBatch.id))
        ).scalars().all()

    # Ikkovi ham natija oladi, lekin GURUH reaksiyasi faqat guruhdagisiga.
    assert all(b.outcome == BatchOutcome.PASSED for b in batches)
    assert _group_reactions(cb) == [(ADMIN_ID, GROUP_ID, GROUP_MSG_ID, "👍")]
    # Lichkadagi rasmga esa ikkovi ham reaksiya oladi — u guruhga
    # tushgan-tushmaganiga bog'liq emas.
    assert {r[2] for r in _dm_reactions(cb)} == {1, 55}
