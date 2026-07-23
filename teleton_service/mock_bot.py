"""Soxta (mock) tekshiruv bot — TZ 10.1.

Real tekshiruv botlar qora quti bo'lib, matnini tanib olish (7.1-bo'lim,
`bot_patterns`) orqali ishlaydi. Mock bot bizning o'z kodimiz bo'lgani uchun
o'z chiqishini qayta tekshirish (parsing) shart emas — to'g'ridan-to'g'ri
tuzilgan natija qaytaradi. Real botga ulanganda (MVP-5) shu klass o'rniga
Telethon orqali xabar yuborib, `bot_patterns` bilan tanib oluvchi adapter
yoziladi — case_manager kodi o'zgarmaydi.
"""

from core.enums import CaseStatus

# TZ 10.1-jadvaldagi standart matnlar
COUPON_REQUEST_TEXT = "Kupon raqamini yuboring."
CONFIRMED_TEXT = "✅ Muvaffaqiyatli! Kupon tasdiqlandi."
EXPIRED_TEXT = "⛔ Kuponning muddati o'tgan."
REJECTED_TEXT = "❌ Bunday kupon topilmadi."

_RESULT_TEXTS = {
    CaseStatus.CONFIRMED: CONFIRMED_TEXT,
    CaseStatus.EXPIRED: EXPIRED_TEXT,
    CaseStatus.REJECTED: REJECTED_TEXT,
}

# Test/sinov uchun oldindan belgilangan kupon -> natija xaritasi.
# Ro'yxatda yo'q har qanday 6 xonali kupon "topilmadi" (REJECTED) deb hisoblanadi.
_TEST_COUPON_OUTCOMES: dict[str, CaseStatus] = {
    "111111": CaseStatus.CONFIRMED,
    "222222": CaseStatus.EXPIRED,
    "333333": CaseStatus.REJECTED,
}


class BotUnresponsiveError(Exception):
    """Mock bot "javob bermayapti" holatini simulyatsiya qilish uchun (TZ 12-bo'lim)."""


class MockVerificationBot:
    """Har nusxa bitta tekshiruv botini ifodalaydi (bot pool'dagi bitta slot).

    `unresponsive_phones` / `unresponsive_coupons` — MVP-3 timeout/retry
    testlari uchun: shu ro'yxatdagi telefon/kupon kelsa, bot javob bermay
    xato ko'taradi (case_manager'ning retry+backoff qatlamini sinash uchun).
    """

    def __init__(
        self,
        extra_outcomes: dict[str, CaseStatus] | None = None,
        unresponsive_phones: set[str] | None = None,
        unresponsive_coupons: set[str] | None = None,
    ) -> None:
        self._outcomes = dict(_TEST_COUPON_OUTCOMES)
        if extra_outcomes:
            self._outcomes.update(extra_outcomes)
        self._unresponsive_phones = unresponsive_phones or set()
        self._unresponsive_coupons = unresponsive_coupons or set()

    async def request_coupon(self, bot, phone: str) -> str:
        """Nomer qabul qilingandan keyin bot javobi (TZ 2-bo'lim, 3-qadam).

        `bot` (pool a'zosi) mock uchun ahamiyatsiz — barcha nusxalar bir xil
        xatti-tutadi; MVP-5'dagi real_bot_adapter buni haqiqiy Telegram bot
        username'i sifatida ishlatadi.
        """
        if phone in self._unresponsive_phones:
            raise BotUnresponsiveError(f"Bot {phone} uchun javob bermayapti (test)")
        return COUPON_REQUEST_TEXT

    async def check_coupon(self, bot, coupon: str) -> tuple[CaseStatus, str]:
        """Kuponni tekshiradi, (natija, bot matni) qaytaradi."""
        if coupon in self._unresponsive_coupons:
            raise BotUnresponsiveError(f"Bot {coupon} uchun javob bermayapti (test)")
        outcome = self._outcomes.get(coupon, CaseStatus.REJECTED)
        return outcome, _RESULT_TEXTS[outcome]
