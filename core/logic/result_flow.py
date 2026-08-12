"""Natija tarqatish — TZ v2 7-bo'lim (B-4).

Aralash rejim (7.1):
| Natija      | Mijozga                    | Guruhga | Adminbotga            |
|-------------|----------------------------|---------|-----------------------|
| PASSED      | avtomatik (soya: yo'q)     | 👍      | ma'lumot xabari       |
| FAILED      | admin tugma bosgach        | 👎      | [Yuborish]/[Yo'q]     |
| UNRECOGNIZED| yozilmaydi                 | ⚠️      | (engine alert bergan) |
| STALLED     | yozilmaydi                 | ⏳      | superadmin alert      |

Soya rejimi (6.4.6, standart YOQILGAN): mijozga hech narsa yozilmaydi —
qolgan hamma narsa (baza, reaksiya, alertlar) odatdagidek ishlaydi.

Kech javob (6.5, foydalanuvchi qarori 1b): natija AVTOMATIK to'g'irlanadi
(baza + reaksiya), adminga "mijozdan uzr so'rab, to'g'ri natijani yozing"
xabari boradi — mijozga TIZIM yozmaydi (uzr insoniy bo'lishi kerak).

Telethon'ga bog'lanmagan — reaksiya qo'yish va mijozga yozish callback'lar
orqali (relay beradi), butun mantiq tarmoqsiz testlanadi.
"""

import datetime
import logging
from contextlib import AbstractAsyncContextManager
from typing import Awaitable, Callable

from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.screenshots import format_phone_pretty
from core.logic.settings_store import is_shadow_mode
from core.logic.templates import get_template
from core.models import (
    BatchOutcome,
    Case,
    CheckRequest,
    CheckResult,
    NotifiedBy,
    OutcomeSource,
    ScreenshotBatch,
    User,
)

log = logging.getLogger("result_flow")

# set_reaction(admin_id, chat_id, message_id, emoji) -> muvaffaqiyatmi
SetReaction = Callable[[int, int, int, str], Awaitable[bool]]
# send_customer(admin_id, customer_tg_id, text) -> muvaffaqiyatmi
SendCustomer = Callable[[int, int, str], Awaitable[bool]]
# failed_confirmation(message, request_id) — tugmali adminbot xabari
FailedConfirmation = Callable[[str, int], Awaitable[None]]
AlertSink = Callable[[str, bool], Awaitable[None]]

REACTION_BY_OUTCOME = {
    BatchOutcome.PASSED: "👍",
    BatchOutcome.FAILED: "👎",
    BatchOutcome.UNKNOWN: "⚠️",
    BatchOutcome.STALLED: "⏳",
}

_OUTCOME_BY_RESULT = {
    CheckResult.PASSED: BatchOutcome.PASSED,
    CheckResult.FAILED: BatchOutcome.FAILED,
    CheckResult.UNRECOGNIZED: BatchOutcome.UNKNOWN,
}


class ResultDistributor:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        alert_sink: AlertSink,
        set_reaction: SetReaction,
        send_customer: SendCustomer,
        failed_confirmation: FailedConfirmation,
    ) -> None:
        self.session_factory = session_factory
        self.alert_sink = alert_sink
        self.set_reaction = set_reaction
        self.send_customer = send_customer
        self.failed_confirmation = failed_confirmation

    # ------------------------------------------------------------------ #
    # Engine hook'lari
    # ------------------------------------------------------------------ #

    async def on_result(
        self, request_id: int, prev_case_status: CaseStatus | None = None
    ) -> None:
        """Tekshiruvchi javobi yakunlangach chaqiriladi (engine result_hook)."""
        async with self.session_factory() as session:
            request = await session.get(CheckRequest, request_id)
            if request is None or request.result is None:
                return
            case = await session.get(Case, request.case_id)
            user = await session.get(User, case.user_id) if case else None

            outcome = _OUTCOME_BY_RESULT.get(request.result)
            if outcome is None:
                return

            code = (case.short_code or case.id) if case else request.case_id
            phone = format_phone_pretty(request.phone)

            # §6.5 (1b) — kech javob: admin allaqachon boshqacha hal qilgan.
            late = (
                prev_case_status in (CaseStatus.PASSED, CaseStatus.FAILED)
                and request.result in (CheckResult.PASSED, CheckResult.FAILED)
                and prev_case_status.value != request.result.value
            )
            if late:
                request.late_corrected = True
                await session.commit()

            await self._update_batch_and_react(session, request, outcome)

            if late:
                new_label = "O'TGAN" if request.result == CheckResult.PASSED else "O'TMAGAN"
                prev_label = "O'TDI" if prev_case_status == CaseStatus.PASSED else "O'TMADI"
                await self.alert_sink(
                    f"⚠️ KECH JAVOB ({code}, {phone}): bu mijozning ovozi aslida "
                    f"{new_label} ekan — siz {prev_label} deb yopgansiz. Natija "
                    f"bazada va guruhda to'g'irlandi. Mijozdan uzr so'rab, "
                    f"to'g'ri natijani O'ZINGIZ yozing.",
                    True,
                )
                return  # mijozga tizim yozmaydi — uzr admin zimmasida

            shadow = await is_shadow_mode(session)

            if request.result == CheckResult.PASSED:
                if shadow:
                    await self.alert_sink(
                        f"🕶 (soya rejimi) {code}: {phone} O'TDI — mijozga "
                        f"yozilmadi.",
                        False,
                    )
                    return
                text = await get_template(session, "RESULT_PASSED")
                ok = (
                    await self.send_customer(
                        request.requested_by_admin_id, user.tg_user_id, text
                    )
                    if user
                    else False
                )
                if ok:
                    request.customer_notified_at = datetime.datetime.utcnow()
                    request.notified_by = NotifiedBy.AUTO
                    await session.commit()
                else:
                    await self.alert_sink(
                        f"⚠️ {code}: O'TDI, lekin mijozga avtomatik yozib "
                        f"bo'lmadi — qo'lda yozing.",
                        True,
                    )
                return

            if request.result == CheckResult.FAILED:
                if shadow:
                    await self.alert_sink(
                        f"🕶 (soya rejimi) {code}: {phone} O'TMADI — mijozga "
                        f"yozilmadi, tasdiqlash tugmasi ham yuborilmadi.",
                        False,
                    )
                    return
                # §7.1 — nozik xabar: admin ko'zi bilan ko'rib tasdiqlaydi.
                customer = (
                    f"@{user.tg_username}" if user and user.tg_username else ""
                ) or (user.display_name if user else "") or "mijoz"
                await self.failed_confirmation(
                    f"❌ {code}: {phone} — ovoz O'TMADI.\n"
                    f"👤 {customer}\n\n"
                    f"Mijozga \"o'tmadi\" xabarini yuboraymi?",
                    request.id,
                )

    async def on_stalled(self, request_id: int) -> None:
        """Stall (6.5) — guruh postiga ⏳ (engine alertni o'zi bergan)."""
        async with self.session_factory() as session:
            request = await session.get(CheckRequest, request_id)
            if request is None or request.replied_at is not None:
                return
            await self._update_batch_and_react(session, request, BatchOutcome.STALLED)

    # ------------------------------------------------------------------ #
    # FAILED tasdiqlangandan keyin yuborish (NOTIFY_FAILED job)
    # ------------------------------------------------------------------ #

    async def send_failed_now(self, request_id: int) -> None:
        """Admin [Mijozga yuborish]ni bosgach — Teleton polleri chaqiradi."""
        async with self.session_factory() as session:
            request = await session.get(CheckRequest, request_id)
            if request is None:
                return
            if request.customer_notified_at is not None:
                return  # allaqachon yuborilgan (takror bosishdan himoya)
            case = await session.get(Case, request.case_id)
            user = await session.get(User, case.user_id) if case else None
            if user is None:
                return
            code = (case.short_code or case.id) if case else request.case_id

            if await is_shadow_mode(session):
                await self.alert_sink(
                    f"🕶 {code}: soya rejimi yoqilgan — 'o'tmadi' xabari "
                    f"mijozga yuborilmadi.",
                    True,
                )
                return

            text = await get_template(session, "RESULT_FAILED")
            ok = await self.send_customer(
                request.requested_by_admin_id, user.tg_user_id, text
            )
            if ok:
                request.customer_notified_at = datetime.datetime.utcnow()
                request.notified_by = NotifiedBy.ADMIN
                await session.commit()
                await self.alert_sink(
                    f"📤 {code}: \"o'tmadi\" xabari mijozga yuborildi.", False
                )
            else:
                await self.alert_sink(
                    f"⚠️ {code}: mijozga yozib bo'lmadi — qo'lda yozing.", True
                )

    # ------------------------------------------------------------------ #
    # Ichki
    # ------------------------------------------------------------------ #

    async def _update_batch_and_react(
        self, session, request: CheckRequest, outcome: BatchOutcome
    ) -> None:
        result = await session.execute(
            select(ScreenshotBatch)
            .where(ScreenshotBatch.case_id == request.case_id)
            .order_by(ScreenshotBatch.id.desc())
        )
        batch = result.scalars().first()
        if batch is None:
            return  # rasmsiz tekshirilgan case — guruh posti yo'q

        batch.outcome = outcome
        batch.outcome_source = OutcomeSource.AUTO
        await session.commit()

        if batch.group_chat_id is None or batch.group_message_id is None:
            return  # guruhga tushmagan partiya

        emoji = REACTION_BY_OUTCOME[outcome]
        ok = await self.set_reaction(
            batch.admin_id, batch.group_chat_id, batch.group_message_id, emoji
        )
        if not ok:
            # §7.3 — reaksiya qo'yilmasa natija bazada saqlanadi + alert.
            await self.alert_sink(
                f"⚠️ Guruhda reaksiya qo'yib bo'lmadi (partiya #{batch.id}, "
                f"{emoji}) — guruh sozlamalarida reaksiyalar yopilgan bo'lishi "
                f"mumkin. Natija bazada saqlangan.",
                True,
            )
