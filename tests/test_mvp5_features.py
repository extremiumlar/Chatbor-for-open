"""MVP-5: bot-tanish shablonlari, bot-xabardor VerificationBot protokoli,
ko'p-akkaunt pool scoping (Q55), real_bot_adapter'ning tarmoqsiz mantig'i.

Haqiqiy tekshiruv botiga ulanish BU YERDA SINALMAYDI (foydalanuvchi hali
ruxsat bermagan) — faqat DB-asoslangan mantiq (pattern matching, pool
scoping, xatolik yo'naltirish) tekshiriladi.
"""

from core.enums import CaseStatus
from core.logic.bot_patterns import (
    REQUIRED_KEYS,
    UnrecognizedBotResponseError,
    all_patterns_configured,
    get_pattern,
    list_patterns,
    missing_patterns,
    recognize,
    set_pattern,
)
from core.logic.bot_pool import BotPoolManager, add_bot, ensure_bots_seeded
from teleton_service.real_bot_adapter import RealVerificationBotAdapter
from tests.test_case_state_machine import _latest_case


# --------------------------------------------------------------------------- #
# Bot-tanish shablonlari (TZ 7.1, 9.4 Q16)
# --------------------------------------------------------------------------- #


async def test_bot_pattern_defaults_to_missing_until_set(session_factory):
    async with session_factory() as session:
        assert await get_pattern(session, "CONFIRMED") is None
        assert await missing_patterns(session) == list(REQUIRED_KEYS)
        assert await all_patterns_configured(session) is False


async def test_setting_all_patterns_satisfies_gate(session_factory):
    async with session_factory() as session:
        for key in REQUIRED_KEYS:
            await set_pattern(session, key, f"namuna-{key}")

        assert await all_patterns_configured(session) is True
        patterns = await list_patterns(session)
        assert patterns["CONFIRMED"] == "namuna-CONFIRMED"


async def test_set_pattern_rejects_unknown_key(session_factory):
    async with session_factory() as session:
        try:
            await set_pattern(session, "NOMALUM", "x")
            assert False, "ValueError kutilgan edi"
        except ValueError:
            pass


def test_recognize_is_case_insensitive_substring_match():
    assert recognize("✅ Muvaffaqiyatli! Kupon tasdiqlandi.", "muvaffaqiyatli") is True
    assert recognize("Boshqa narsa", "muvaffaqiyatli") is False


# --------------------------------------------------------------------------- #
# VerificationBot protokoli endi bot-xabardor (MVP-5 arxitektura tuzatishi)
# --------------------------------------------------------------------------- #


class _RecordingBot:
    """Qaysi pool a'zosi (bot.username) orqali chaqirilganini yozib boradi."""

    def __init__(self, outcomes: dict[str, CaseStatus] | None = None) -> None:
        self.requested: list[tuple[str, str]] = []
        self.checked: list[tuple[str, str]] = []
        self._outcomes = outcomes or {}

    async def request_coupon(self, bot, phone: str) -> str:
        self.requested.append((bot.username, phone))
        return "ok"

    async def check_coupon(self, bot, coupon: str) -> tuple[CaseStatus, str]:
        self.checked.append((bot.username, coupon))
        return self._outcomes.get(coupon, CaseStatus.REJECTED), "matn"


async def test_bot_client_receives_correct_bot_identity(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    recorder = _RecordingBot({"111111": CaseStatus.CONFIRMED})
    cm = make_case_manager(bot_client=recorder)

    await cm.handle_phone_detected(1101, "u1", "U1", "998901234567")
    await cm.handle_coupon_received(1101, "111111")

    assert recorder.requested == [("bot1", "+998901234567")]
    assert recorder.checked == [("bot1", "111111")]


class _UnrecognizedBot:
    def __init__(self) -> None:
        self.check_calls = 0

    async def request_coupon(self, bot, phone: str) -> str:
        return "ok"

    async def check_coupon(self, bot, coupon: str) -> tuple[CaseStatus, str]:
        self.check_calls += 1
        raise UnrecognizedBotResponseError("g'alati javob")


async def test_unrecognized_bot_response_escalates_to_needs_admin_without_retry(
    seed_bots, make_case_manager, session_factory
):
    # TZ 8-bo'lim — bot javob berdi, faqat tanilmadi -> NEEDS_ADMIN, qayta
    # urinish emas (TIMEOUT yo'lidan farqli).
    await seed_bots(["bot1"])
    bot_client = _UnrecognizedBot()
    alerts = []

    async def capture_alert(message, important=True):
        alerts.append((message, important))

    cm = make_case_manager(bot_client=bot_client, alert_sink=capture_alert, bot_response_max_retries=3)

    await cm.handle_phone_detected(1102, "u2", "U2", "998902222222")
    outcome = await cm.handle_coupon_received(1102, "999999")

    assert outcome.customer_text is None
    assert bot_client.check_calls == 1  # qayta urinilmadi

    case = await _latest_case(session_factory, 1102)
    assert case.status == CaseStatus.NEEDS_ADMIN
    assert any("tanilmadi" in m and important for m, important in alerts)


# --------------------------------------------------------------------------- #
# Ko'p-akkaunt pool scoping (Q55 — "har admin+bot mustaqil slot")
# --------------------------------------------------------------------------- #


async def test_pool_scoping_keeps_admin_bots_independent(session_factory):
    async with session_factory() as session:
        await ensure_bots_seeded(session, ["shared_bot"])  # owner_admin_id=None
        await add_bot(session, "admin5_bot", owner_admin_id=5)

    shared_pool = BotPoolManager()
    admin5_pool = BotPoolManager(owner_admin_id=5)

    async with session_factory() as session:
        shared_bot = await shared_pool.acquire(session, case_id=1)
        assert shared_bot.username == "shared_bot"

        admin5_bot = await admin5_pool.acquire(session, case_id=2)
        assert admin5_bot.username == "admin5_bot"

        # admin5 pool'ning yagona boti band — umumiy (owner=None) botga
        # "sizib o'tmaydi", shunchaki navbatga tushadi.
        still_none = await admin5_pool.acquire(session, case_id=3)
        assert still_none is None
        assert admin5_pool.queue_length == 1


async def test_case_manager_owner_admin_id_scopes_its_pool(seed_bots, make_case_manager, session_factory):
    async with session_factory() as session:
        await add_bot(session, "admin7_bot", owner_admin_id=7)
    await seed_bots(["shared_bot_x"])  # umumiy pool uchun

    cm_admin7 = make_case_manager()
    cm_admin7.pool = BotPoolManager(
        on_assigned=cm_admin7._on_queued_case_assigned, owner_admin_id=7
    )

    outcome = await cm_admin7.handle_phone_detected(1201, "u3", "U3", "998903333333")
    assert outcome.customer_text is not None  # admin7_bot orqali dispatch bo'ldi

    case = await _latest_case(session_factory, 1201)
    async with session_factory() as session:
        from core.models import Bot

        bot = await session.get(Bot, case.bot_id)
        assert bot.username == "admin7_bot"


# --------------------------------------------------------------------------- #
# RealVerificationBotAdapter — faqat tarmoqsiz klassifikatsiya mantig'i
# --------------------------------------------------------------------------- #


async def test_real_bot_adapter_classifies_using_configured_patterns(session_factory):
    async with session_factory() as session:
        await set_pattern(session, "CONFIRMED", "muvaffaqiyatli")
        await set_pattern(session, "EXPIRED", "muddati o'tgan")
        await set_pattern(session, "REJECTED", "topilmadi")
        await set_pattern(session, "COUPON_REQUEST", "kupon")

    adapter = RealVerificationBotAdapter(client=None, session_factory=session_factory)

    assert await adapter._classify("✅ Muvaffaqiyatli! Tabriklaymiz.") == CaseStatus.CONFIRMED
    assert await adapter._classify("Kuponning muddati o'tgan ekan.") == CaseStatus.EXPIRED
    assert await adapter._classify("Bunday kupon topilmadi.") == CaseStatus.REJECTED
    assert await adapter._classify("Tushunarsiz boshqa xabar.") is None


async def test_real_bot_adapter_check_coupon_raises_when_unrecognized(session_factory):
    async with session_factory() as session:
        await set_pattern(session, "CONFIRMED", "muvaffaqiyatli")
        await set_pattern(session, "EXPIRED", "muddati o'tgan")
        await set_pattern(session, "REJECTED", "topilmadi")
        await set_pattern(session, "COUPON_REQUEST", "kupon")

    class _FakeConversation:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send_message(self, text):
            pass

        async def get_response(self):
            class _Msg:
                raw_text = "Bu butunlay tushunarsiz javob."

            return _Msg()

    class _FakeClient:
        def conversation(self, username, timeout=None):
            return _FakeConversation()

    adapter = RealVerificationBotAdapter(client=_FakeClient(), session_factory=session_factory)

    class _FakeBot:
        id = 1
        username = "fake_bot"
        needs_start_greeting = False

    try:
        await adapter.check_coupon(_FakeBot(), "123456")
        assert False, "UnrecognizedBotResponseError kutilgan edi"
    except UnrecognizedBotResponseError:
        pass
