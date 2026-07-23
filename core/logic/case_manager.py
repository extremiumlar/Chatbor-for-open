"""Case state machine — TZ 2, 5, 6, 9, 12-bo'lim.

MVP-3: EXPIRED-qayta-urinish sikli (2.1, Q57/58/59), shubhali-holat aniqlash
(5.2), rasm-xato ishlovi (5.1), tekshiruv bot javob bermasa timeout/retry
(12-bo'lim) qo'shildi.

Foydalanuvchi tomonidan javobsiz qoldirilgan (ammo tavsiya etilgan variant
bilan davom etilgan) taxminlar — README.md "MVP-3 taxminlari" bo'limiga
qarang: (a) NEEDS_ADMIN'da mijozga oddiy EXPIRED_RETRY matni ko'rsatiladi
(alohida shablon yo'q), (b) TIMEOUT'da mijozga hech qanday avtomatik javob
yo'q (shablon yo'q, admin qo'lda kuzatadi), (c) bloklangan foydalanuvchidan
kelgan har qanday xabar butunlay jim e'tiborsiz qoldiriladi, (d) EXPIRED
holatida FARQLI nomer kelsa DUPLICATE_ACTIVE kabi ishlov beriladi.
"""

import asyncio
import datetime
import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, TypeVar

from sqlalchemy import select

from core.config import settings
from core.enums import ACTIVE_STATUSES, CaseStatus
from core.logic.bot_pool import BotPoolManager
from core.logic.bot_patterns import UnrecognizedBotResponseError
from core.logic.phone import format_for_bot
from core.logic.templates import get_template
from core.models import Bot, Case, CouponAttempt, User

log = logging.getLogger("case_manager")

T = TypeVar("T")


class VerificationBot(Protocol):
    """MVP-5: metodlar `bot` (pool a'zosi, `bot.username`) ni ham qabul qiladi —
    real ko'p-bot rejimida qaysi Telegram bot bilan gaplashish kerakligini
    bilish uchun shart (MockVerificationBot buni e'tiborsiz qoldiradi,
    real_bot_adapter esa aynan shu orqali to'g'ri suhbatni tanlaydi)."""

    async def request_coupon(self, bot: Bot, phone: str) -> str: ...
    async def check_coupon(self, bot: Bot, coupon: str) -> tuple[CaseStatus, str]: ...


@dataclass
class RelayOutcome:
    """Mijozga darhol yuboriladigan javob (agar bo'lsa)."""

    customer_text: str | None = None


async def _default_alert(message: str, important: bool = True) -> None:
    log.info("ADMIN ALERT: %s", message)


async def _default_suspicious_alert(
    message: str, case_id: int, tg_user_id: int, tg_username: str | None
) -> None:
    log.warning("SUSPICIOUS ALERT (case #%s): %s", case_id, message)


async def _default_image_warning(message: str, tg_user_id: int, tg_username: str | None) -> None:
    log.warning("IMAGE WARNING: %s", message)


class CaseManager:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        bot_client: VerificationBot,
        alert_sink: Callable[[str, bool], Awaitable[None]] = _default_alert,
        notify_customer: Callable[[int, str], Awaitable[None]] | None = None,
        customer_timeout_seconds: float | None = None,
        suspicious_alert_sink: Callable[
            [str, int, int, str | None], Awaitable[None]
        ] = _default_suspicious_alert,
        image_warning_sink: Callable[[str, int, str | None], Awaitable[None]] = _default_image_warning,
        bot_response_max_retries: int | None = None,
        bot_response_backoff_seconds: float | None = None,
        owner_admin_id: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.bot_client = bot_client
        self.alert_sink = alert_sink
        self.notify_customer = notify_customer or (lambda tg_user_id, text: _noop())
        self.customer_timeout_seconds = (
            customer_timeout_seconds
            if customer_timeout_seconds is not None
            else settings.customer_coupon_timeout_seconds
        )
        self.suspicious_alert_sink = suspicious_alert_sink
        self.image_warning_sink = image_warning_sink
        self.bot_response_max_retries = (
            bot_response_max_retries
            if bot_response_max_retries is not None
            else settings.bot_response_max_retries
        )
        self.bot_response_backoff_seconds = (
            bot_response_backoff_seconds
            if bot_response_backoff_seconds is not None
            else settings.bot_response_backoff_seconds
        )
        self.pool = BotPoolManager(
            on_assigned=self._on_queued_case_assigned, owner_admin_id=owner_admin_id
        )
        self._customer_timers: dict[int, asyncio.Task] = {}

    # ------------------------------------------------------------------ #
    # Ommaviy hodisalar (Teleton relay shu metodlarni chaqiradi)
    # ------------------------------------------------------------------ #

    async def handle_phone_detected(
        self, tg_user_id: int, tg_username: str | None, display_name: str | None, phone: str
    ) -> RelayOutcome:
        async with self.session_factory() as session:
            user = await self._get_or_create_user(session, tg_user_id, tg_username, display_name)

            if user.is_blocked:
                # TZ 5.2 (Bloklash oqibati) — bloklangan foydalanuvchi butunlay jim qoldiriladi.
                return RelayOutcome(customer_text=None)

            latest_case = await self._get_latest_case(session, user.id)

            if latest_case is not None and latest_case.status in ACTIVE_STATUSES:
                # TZ 2.3 (Q49) — faol case bor holatda yangi nomer botga yuborilmaydi.
                return await self._hold_as_duplicate_active(session, user, phone, latest_case)

            if latest_case is not None and latest_case.status == CaseStatus.EXPIRED:
                if latest_case.phone == phone:
                    # TZ 2.1 (Q57) — AYNAN O'SHA nomer qaytadan kelsa, SHU case'ning
                    # yangi urinishi (case_id o'zgarmaydi, bot yangidan tanlanadi).
                    return await self._dispatch_to_bot(session, latest_case)
                # Farqli nomer — eski case hali "hal bo'lmagan" deb hisoblanadi (TZ
                # aniq javob bermagan joy, DUPLICATE_ACTIVE'ga o'xshatib ishlov berildi).
                return await self._hold_as_duplicate_active(session, user, phone, latest_case)

            if latest_case is not None and latest_case.status in (
                CaseStatus.NEEDS_ADMIN,
                CaseStatus.SUSPICIOUS_HOLD,
            ):
                # Admin aralashuvi kutilayotgan case — avtomatik qayta urinish yo'q.
                return await self._hold_as_duplicate_active(session, user, phone, latest_case)

            if await self._find_confirmed_case_by_phone(session, phone) is not None:
                # TZ 2.4 (Q50) — tasdiqlangan nomer botga yuborilmaydi.
                text = await get_template(session, "ALREADY_CONFIRMED")
                return RelayOutcome(customer_text=text)

            other_case = await self._find_other_users_case_by_phone(session, phone, user.id)
            if other_case is not None:
                # TZ 5.2 — bitta nomer turli telegram akkauntlaridan.
                return await self._hold_as_suspicious(session, user, phone, other_case)

            case = Case(user_id=user.id, phone=phone, status=CaseStatus.NUMBER_RECEIVED)
            session.add(case)
            await session.commit()
            await session.refresh(case)

            return await self._dispatch_to_bot(session, case)

    async def handle_coupon_received(
        self, tg_user_id: int, coupon: str
    ) -> RelayOutcome | None:
        async with self.session_factory() as session:
            user = await self._get_user(session, tg_user_id)
            if user is None or user.is_blocked:
                return None

            case = await self._get_latest_case(session, user.id)
            if case is None:
                return None

            if case.status == CaseStatus.CUSTOMER_TIMEOUT:
                # TZ 2.2 — timeoutdan keyin kelgan xabarga shu matn bilan javob.
                text = await get_template(session, "EXPIRED_RETRY")
                return RelayOutcome(customer_text=text)

            if case.status != CaseStatus.AWAITING_COUPON:
                return None  # bu kontekstda kupon kutilmayapti — oddiy chat xabari

            if await self._is_duplicate_expired_coupon(session, case.id, coupon):
                # TZ 2.1 (Q58) — eskisi bilan bir xil (allaqachon muddati o'tgan)
                # kupon qayta yuborilsa, botga yuborilmaydi.
                text = await get_template(session, "DUPLICATE_COUPON")
                return RelayOutcome(customer_text=text)

            self._cancel_customer_timer(case.id)

            case.status = CaseStatus.COUPON_SENT_TO_BOT
            case.current_coupon = coupon
            bot = await session.get(Bot, case.bot_id)
            await session.commit()

            try:
                result_status, _bot_text = await self._call_bot(
                    lambda: self.bot_client.check_coupon(bot, coupon)
                )
            except UnrecognizedBotResponseError as exc:
                await self._handle_unrecognized_response(
                    session, case, case.bot_id, tg_user_id, str(exc)
                )
                return RelayOutcome(customer_text=None)
            except Exception:
                await self._handle_bot_timeout(session, case, case.bot_id, tg_user_id)
                return RelayOutcome(customer_text=None)

            session.add(
                CouponAttempt(
                    case_id=case.id, coupon=coupon, result=result_status, bot_id=case.bot_id
                )
            )

            bot_id = case.bot_id

            if result_status == CaseStatus.CONFIRMED:
                case.status = CaseStatus.CONFIRMED
                case.confirmed_at = datetime.datetime.utcnow()
                await session.commit()
                await self.pool.release(session, bot_id)
                # TZ 9.1 — tasdiq "muhim" hodisa, verbose rejimidan qat'i nazar yuboriladi.
                await self._alert(f"Case #{case.id} CONFIRMED (tg_id={tg_user_id}).", important=True)
                text = await get_template(session, "CONFIRMED")
                return RelayOutcome(customer_text=text)

            if result_status == CaseStatus.REJECTED:
                case.status = CaseStatus.REJECTED
                await session.commit()
                await self.pool.release(session, bot_id)
                # TZ 9.1 — rad ham "muhim" hodisa.
                await self._alert(f"Case #{case.id} REJECTED (tg_id={tg_user_id}).", important=True)
                text = await get_template(session, "REJECTED")
                return RelayOutcome(customer_text=text)

            # EXPIRED — TZ 2.1 qayta-urinish sikli (Q57/58/59).
            case.expired_attempts += 1
            await self.pool.release(session, bot_id)  # 2.1/3.5 — bot darhol bo'shaydi

            if case.expired_attempts >= 5:
                case.status = CaseStatus.NEEDS_ADMIN
                await session.commit()
                await self._alert(
                    f"Case #{case.id} {case.expired_attempts} marta EXPIRED -> "
                    f"NEEDS_ADMIN (tg_id={tg_user_id}).",
                    important=True,
                )
            else:
                case.status = CaseStatus.EXPIRED
                await session.commit()
                # TZ 9.1'dagi sukut "muhim" ro'yxatida yo'q -> faqat batafsil rejimda.
                await self._alert(
                    f"Case #{case.id} EXPIRED ({case.expired_attempts}/5) (tg_id={tg_user_id}).",
                    important=False,
                )

            text = await get_template(session, "EXPIRED_RETRY")
            return RelayOutcome(customer_text=text)

    async def handle_non_text_coupon_input(
        self, tg_user_id: int, tg_username: str | None, display_name: str | None
    ) -> RelayOutcome | None:
        """TZ 5.1 — mijoz kupon o'rniga rasm/media yuborsa."""
        async with self.session_factory() as session:
            user = await self._get_user(session, tg_user_id)
            if user is None or user.is_blocked:
                return None

            case = await self._get_latest_case(session, user.id)
            if case is None or case.status != CaseStatus.AWAITING_COUPON:
                return None  # kupon kutilmayapti — bu holatda rasm oddiy suhbat xabari

            text = await get_template(session, "IMAGE_INSTEAD_OF_TEXT")
            await self._image_warning(
                f"Mijoz (tg_id={tg_user_id}, @{tg_username or '-'}, {display_name or '-'}) "
                f"kupon o'rniga rasm/media yubordi. Case #{case.id}.",
                tg_user_id,
                tg_username,
            )
            return RelayOutcome(customer_text=text)

    # ------------------------------------------------------------------ #
    # Bot dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch_to_bot(self, session, case: Case) -> RelayOutcome:
        bot = await self.pool.acquire(session, case.id)
        if bot is None:
            # TZ 3.1 (Q45) — hamma bot band, case navbatga tushdi (har doim xabar berilishi shart).
            await self._alert(
                f"Hamma tekshiruv bot band. Case #{case.id} navbatga qo'yildi.", important=True
            )
            return RelayOutcome(customer_text=None)

        case.status = CaseStatus.SENT_TO_BOT
        case.bot_id = bot.id
        await session.commit()

        text = await self._send_coupon_request(session, case, bot)
        return RelayOutcome(customer_text=text)

    async def _send_coupon_request(self, session, case: Case, bot: Bot) -> str | None:
        phone_for_bot = format_for_bot(case.phone, bot.phone_format)
        try:
            await self._call_bot(lambda: self.bot_client.request_coupon(bot, phone_for_bot))
        except Exception:
            await self._handle_bot_timeout(session, case, bot.id, case.user_id)
            return None

        case.status = CaseStatus.AWAITING_COUPON
        await session.commit()

        self._start_customer_timer(case.id)
        return await get_template(session, "COUPON_REQUEST")

    async def _on_queued_case_assigned(self, case_id: int, bot_id: int) -> None:
        """Navbatda turgan case'ga bot bo'shagach avtomatik tayinlanganda (Q45)."""
        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            user = await session.get(User, case.user_id)
            bot = await session.get(Bot, bot_id)

            case.status = CaseStatus.SENT_TO_BOT
            case.bot_id = bot_id
            await session.commit()

            text = await self._send_coupon_request(session, case, bot)
            if text is not None:
                await self.notify_customer(user.tg_user_id, text)

    # ------------------------------------------------------------------ #
    # Tekshiruv bot javob bermasa — timeout/retry (TZ 12-bo'lim)
    # ------------------------------------------------------------------ #

    async def _call_bot(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.bot_response_max_retries):
            try:
                return await coro_factory()
            except UnrecognizedBotResponseError:
                # TZ 8-bo'lim — bot JAVOB BERDI, faqat tanilmadi. Qayta urinish
                # foydasiz (bot xuddi shu noaniq javobni yana beradi), darhol
                # chaqiruvchiga ko'tariladi (NEEDS_ADMIN'ga o'tkazish uchun).
                raise
            except Exception as exc:  # bot qora quti — har qanday xato bo'lishi mumkin
                last_exc = exc
                if attempt < self.bot_response_max_retries - 1:
                    await asyncio.sleep(self.bot_response_backoff_seconds * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def _handle_bot_timeout(self, session, case: Case, bot_id: int, tg_user_id: int) -> None:
        case.status = CaseStatus.TIMEOUT
        await session.commit()
        await self.pool.force_release(session, bot_id)
        # TZ 9.1 — "timeout" sukut muhim ro'yxatida. Mijozga shablon TZ'da
        # belgilanmagan (taxmin: jim, admin qo'lda kuzatadi).
        await self._alert(
            f"Tekshiruv bot javob bermadi ({self.bot_response_max_retries} urinishdan keyin). "
            f"Case #{case.id} TIMEOUT (tg_id={tg_user_id}).",
            important=True,
        )

    async def _handle_unrecognized_response(
        self, session, case: Case, bot_id: int, tg_user_id: int, raw_text: str
    ) -> None:
        # TZ 8-bo'lim — "Bot javobi tanilmagan/noaniq format" -> NEEDS_ADMIN
        # (TIMEOUT emas: bot javob berdi, faqat tushunarsiz edi).
        case.status = CaseStatus.NEEDS_ADMIN
        await session.commit()
        await self.pool.force_release(session, bot_id)
        await self._alert(
            f"Tekshiruv bot javobi tanilmadi (noaniq format). Case #{case.id} "
            f"NEEDS_ADMIN (tg_id={tg_user_id}). Xom javob: {raw_text!r}",
            important=True,
        )

    # ------------------------------------------------------------------ #
    # Shubhali holat — bir nomer turli akkauntdan (TZ 5.2)
    # ------------------------------------------------------------------ #

    async def _hold_as_suspicious(self, session, user: User, phone: str, other_case: Case) -> RelayOutcome:
        case = Case(user_id=user.id, phone=phone, status=CaseStatus.SUSPICIOUS_HOLD)
        session.add(case)
        user.is_safe = False
        await session.commit()
        await session.refresh(case)

        await self._suspicious_alert(
            f"SHUBHALI: nomer {phone} boshqa akkauntdan ham kelgan "
            f"(oldingi user_id={other_case.user_id}, case #{other_case.id}). "
            f"Joriy: tg_id={user.tg_user_id}, @{user.tg_username or '-'}.",
            case.id,
            user.tg_user_id,
            user.tg_username,
        )
        # TZ 5.2'da mijozga aniq matn belgilanmagan — jim qoldiriladi (taxmin).
        return RelayOutcome(customer_text=None)

    async def resume_suspicious_case(self, session, case: Case) -> RelayOutcome:
        """Admin 'Xavfsiz' deb belgilagach case'ni dispatch qiladi.

        Teleton alohida jarayon bo'lgani uchun (adminbot to'g'ridan-to'g'ri
        chaqira olmaydi) bu metod `teleton_service.relay`dagi fon vazifasi
        (poller) tomonidan chaqiriladi — TZ 13.1.
        """
        return await self._dispatch_to_bot(session, case)

    async def redispatch_queued_case(self, session, case: Case) -> RelayOutcome:
        """Restart reconciliation uchun (TZ 12-bo'lim, Q37) — hali botga hech
        narsa yuborilmagan (`NUMBER_RECEIVED`, navbatdagi) case'ni xavfsiz
        qayta dispatch qiladi. Hech qanday ma'lumot yo'qolmagani uchun
        oddiy dispatch bilan bir xil (NEEDS_ADMIN'ga o'tkazish shart emas)."""
        return await self._dispatch_to_bot(session, case)

    # ------------------------------------------------------------------ #
    # Mijoz 5-daqiqalik kupon-timeout (TZ 2.2, Q48)
    # ------------------------------------------------------------------ #

    def _start_customer_timer(self, case_id: int) -> None:
        self._cancel_customer_timer(case_id)
        self._customer_timers[case_id] = asyncio.create_task(
            self._customer_timeout_watch(case_id)
        )

    def _cancel_customer_timer(self, case_id: int) -> None:
        task = self._customer_timers.pop(case_id, None)
        if task is not None:
            task.cancel()

    async def _customer_timeout_watch(self, case_id: int) -> None:
        try:
            await asyncio.sleep(self.customer_timeout_seconds)
        except asyncio.CancelledError:
            return

        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None or case.status != CaseStatus.AWAITING_COUPON:
                return  # kupon allaqachon kelgan yoki case boshqa yo'l bilan yopilgan

            bot_id = case.bot_id
            case.status = CaseStatus.CUSTOMER_TIMEOUT
            await session.commit()
            await self.pool.release(session, bot_id)
            # TZ 9.1 — timeout sukut "muhim" ro'yxatida.
            await self._alert(
                f"Mijoz 5 daqiqada kupon yubormadi. Case #{case_id} CUSTOMER_TIMEOUT.",
                important=True,
            )

        self._customer_timers.pop(case_id, None)

    # ------------------------------------------------------------------ #
    # Yordamchi DB so'rovlari
    # ------------------------------------------------------------------ #

    async def _get_or_create_user(
        self, session, tg_user_id: int, tg_username: str | None, display_name: str | None
    ) -> User:
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        user = result.scalars().first()
        if user is None:
            user = User(
                tg_user_id=tg_user_id, tg_username=tg_username, display_name=display_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    async def _get_user(self, session, tg_user_id: int) -> User | None:
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        return result.scalars().first()

    async def _get_latest_case(self, session, user_id: int) -> Case | None:
        # id bo'yicha tartiblanadi, created_at emas — SQLite CURRENT_TIMESTAMP
        # faqat soniya aniqligida bo'lgani uchun tez ketma-ket kelgan case'lar
        # bir xil created_at qiymatiga ega bo'lishi mumkin.
        result = await session.execute(
            select(Case).where(Case.user_id == user_id).order_by(Case.id.desc())
        )
        return result.scalars().first()

    async def _find_confirmed_case_by_phone(self, session, phone: str) -> Case | None:
        result = await session.execute(
            select(Case).where(Case.phone == phone, Case.status == CaseStatus.CONFIRMED)
        )
        return result.scalars().first()

    async def _find_other_users_case_by_phone(
        self, session, phone: str, exclude_user_id: int
    ) -> Case | None:
        result = await session.execute(
            select(Case)
            .where(Case.phone == phone, Case.user_id != exclude_user_id)
            .order_by(Case.id.desc())
        )
        return result.scalars().first()

    async def _is_duplicate_expired_coupon(self, session, case_id: int, coupon: str) -> bool:
        result = await session.execute(
            select(CouponAttempt.id).where(
                CouponAttempt.case_id == case_id,
                CouponAttempt.coupon == coupon,
                CouponAttempt.result == CaseStatus.EXPIRED,
            )
        )
        return result.scalars().first() is not None

    async def _hold_as_duplicate_active(
        self, session, user: User, phone: str, existing_case: Case
    ) -> RelayOutcome:
        duplicate = Case(user_id=user.id, phone=phone, status=CaseStatus.DUPLICATE_ACTIVE)
        session.add(duplicate)
        await session.commit()
        text = await get_template(session, "DUPLICATE_ACTIVE")
        await self._alert(
            f"Mijoz (tg_id={user.tg_user_id}) ikkinchi nomer yubordi ({phone}), "
            f"joriy case #{existing_case.id} hali hal bo'lmagan "
            f"({existing_case.status.value}).",
            important=True,
        )
        return RelayOutcome(customer_text=text)

    async def _alert(self, message: str, important: bool = True) -> None:
        await self.alert_sink(message, important)

    async def _suspicious_alert(
        self, message: str, case_id: int, tg_user_id: int, tg_username: str | None
    ) -> None:
        await self.suspicious_alert_sink(message, case_id, tg_user_id, tg_username)

    async def _image_warning(self, message: str, tg_user_id: int, tg_username: str | None) -> None:
        await self.image_warning_sink(message, tg_user_id, tg_username)


async def _noop(*args, **kwargs) -> None:
    return None
