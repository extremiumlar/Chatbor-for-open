"""Audit N-3 — AdminNotifier'ning ichki aiogram.Bot HTTP-sessiyasi
to'xtatilganda tozalab yopilishi kerak (resurs oqishining oldini olish)."""

from core.logic.notifier import AdminNotifier


async def test_close_closes_underlying_bot_session():
    async def _session_factory():
        raise AssertionError("bu testda chaqirilmasligi kerak")

    notifier = AdminNotifier(session_factory=_session_factory, bot_token="123456:fake-token")
    assert notifier._bot is not None

    # Hech qanday HTTP so'rov yuborilmagani uchun ichki aiohttp sessiyasi
    # hali umuman yaratilmagan (lazy) — asosiy tekshiruv: close() xato
    # bermasdan, ikki marta chaqirilsa ham (idempotent) bajarilishi kerak.
    await notifier.close()
    await notifier.close()


async def test_close_is_noop_when_token_missing():
    async def _session_factory():
        raise AssertionError("bu testda chaqirilmasligi kerak")

    notifier = AdminNotifier(session_factory=_session_factory, bot_token="")
    assert notifier._bot is None
    await notifier.close()  # xato bermasligi kerak
