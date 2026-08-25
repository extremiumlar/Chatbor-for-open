"""Tekshiruv dvigateli — TZ v2 6-bo'lim (B-3).

Vazifalari:
- **Navbat**: so'rovlar bazada (`check_requests`), restart'dan omon qoladi.
- **Drip** (6.2): har tick'da KO'PI BILAN BITTA so'rov chiqadi — tekshiruvchi
  (tirik odam) bosim ostida qolmasin. Har admin chatida bir vaqtda faqat
  bitta ochiq so'rov (6.3) — javob-moslashuv chalkashmasin.
- **Kesh** (6.6): yaqinda tekshirilgan nomer qayta so'ralsa, tekshiruvchi
  bezovta qilinmaydi.
- **Javobni bog'lash** (6.4.5): reply > oxirgi-4-raqam > FIFO.
- **Stall** (6.5): javob kelmasa so'rov YO'QOLMAYDI, superadminga alert.

Telethon'ga bog'lanmagan: xabar yuborish `send_to_checker(admin_id, text)`
callback orqali (relay beradi) — butun mantiq tarmoqsiz testlanadi.

B-4 chegarasi: natija MIJOZGA yetkazish, guruh reaksiyasi, kech-javob
to'g'irlash (§6.5 oxiri) bu modulda EMAS — natija bazaga yozilgach B-4
tarqatadi. Hozircha adminlarga alert bilan bildiriladi.
"""

import datetime
import logging
import re
from contextlib import AbstractAsyncContextManager
from typing import Awaitable, Callable

from sqlalchemy import select

from core.enums import CaseStatus, V2_OPEN_STATUSES
from core.logic.check_patterns import (
    AmbiguousMatch,
    CheckCategory,
    classify,
    get_all_patterns,
    missing_categories,
)
from core.logic.settings_store import (
    MIN_CHECK_DELAY_MINUTES,
    get_check_cache_minutes,
    get_check_request_template,
    get_checker_account,
    get_checker_stall_minutes,
)
from core.models import (
    Admin,
    Case,
    CheckRequest,
    CheckResult,
    CheckTrigger,
    JobKind,
    ScheduledJob,
    ScreenshotBatch,
)

log = logging.getLogger("check_engine")

# send_to_checker(admin_id, text) -> yuborilgan xabar id (muvaffaqiyatsiz: None)
SendToChecker = Callable[[int, str], Awaitable[int | None]]
AlertSink = Callable[[str, bool], Awaitable[None]]

_DIGIT_RUN_RE = re.compile(r"\d{4,}")

_RESULT_BY_CATEGORY = {
    CheckCategory.CHECK_PASSED: (CheckResult.PASSED, CaseStatus.PASSED),
    CheckCategory.CHECK_FAILED: (CheckResult.FAILED, CaseStatus.FAILED),
    # "Xato/qayta yuboring" — javob bor, lekin natija emas: admin ko'rsin.
    CheckCategory.CHECK_ERROR: (CheckResult.UNRECOGNIZED, CaseStatus.NEEDS_ADMIN),
}


class CheckEngine:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        alert_sink: AlertSink,
        send_to_checker: SendToChecker,
        result_hook: Callable[[int, CaseStatus | None], Awaitable[None]] | None = None,
        stalled_hook: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.alert_sink = alert_sink
        self.send_to_checker = send_to_checker
        # B-4 — natija tarqatish (ResultDistributor): natija yakunlangach
        # (request_id, avvalgi case holati) bilan chaqiriladi; stalled_hook
        # esa javobsizlik aniqlanganda. None bo'lsa (testlar) — jim.
        self.result_hook = result_hook
        self.stalled_hook = stalled_hook
        # Tayyor-emaslik alerti bir marta beriladi (spam emas); tuzatilgach
        # bayroq tushadi va keyingi muammoda yana beriladi.
        self._not_ready_alerted = False
        # B-6 — yuborilmagan so'rov alerti HAR TICK'da emas, so'rov boshiga
        # BIR MARTA (drip har 20 soniyada aylanadi — aks holda spam bo'lardi).
        self._send_failure_alerted: set[int] = set()

    # ------------------------------------------------------------------ #
    # So'rov qo'yish (qo'lda /check yoki avtomatik CHECK_DUE)
    # ------------------------------------------------------------------ #

    async def request_check(
        self,
        case_id: int,
        trigger: CheckTrigger,
        requested_by_admin_id: int | None = None,
    ) -> str:
        """So'rovni navbatga qo'yadi. Qaytaradi: odam o'qiydigan holat matni
        (adminga qisqa javob berish uchun)."""
        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None:
                return "Case topilmadi."

            admin_id = requested_by_admin_id or case.assigned_admin_id
            if admin_id is None:
                return "Case'ga admin biriktirilmagan."

            # Dublikat himoyasi: shu case uchun ochiq so'rov bormi.
            open_req = await self._find_open_request_for_case(session, case.id)
            if open_req is not None:
                return "Bu case uchun so'rov allaqachon navbatda."

            now = datetime.datetime.utcnow()

            # 70 DAQIQA CHEGARASI — ikkala yo'lda ham amal qiladi.
            #
            # Avtomatik yo'lda vaqtni CHECK_DUE taymeri belgilaydi va u
            # `get_check_delay_minutes`dan oladi (70).
            #
            # Qo'lda `/check` ham SHU chegaraga bo'ysunadi: ovoz
            # tekshiruvchining bazasiga darhol tushmaydi, erta so'ralsa
            # "bazada yo'q" javobi keladi va tizim buni noto'g'ri O'TMADI
            # deb yozadi — mijozning ovozi aslida o'tgan bo'lsa ham. Ya'ni
            # erta so'rov shunchaki foydasiz emas, XATO NATIJA yaratadi.
            #
            # AUTO ataylab tekshirilmaydi: vaqti kelib ishga tushgan
            # CHECK_DUE ishi sekundlik farq tufayli rad etilsa, case
            # abadiy tekshirilmay qolishi mumkin edi.
            qolgan = (
                await self._minutes_until_check_allowed(session, case.id, now)
                if trigger == CheckTrigger.MANUAL
                else 0
            )
            if qolgan > 0:
                o_tgan = MIN_CHECK_DELAY_MINUTES - qolgan
                return (
                    f"⏳ Hali erta — rasm tashlanganiga {o_tgan} daqiqa bo'ldi.\n\n"
                    f"Tekshiruv rasm tashlangandan <b>70 daqiqa</b> keyin "
                    f"boshlanadi: ovoz tekshiruvchining bazasiga darhol "
                    f"tushmaydi, erta so'rasak \"bazada yo'q\" javobi keladi "
                    f"va tizim buni noto'g'ri O'TMADI deb yozadi.\n\n"
                    f"Yana <b>{qolgan} daqiqa</b> kuting — yoki hech narsa "
                    f"qilmang, vaqti kelganda tizim o'zi tekshiradi."
                )

            # §6.6 — kesh: yaqinda AYNAN SHU nomer bo'yicha natija chiqqanmi.
            cache_minutes = await get_check_cache_minutes(session)
            cached = await self._find_recent_result(
                session, case.phone, now - datetime.timedelta(minutes=cache_minutes)
            )

            is_recheck = case.status == CaseStatus.FAILED  # §6.1 a4

            request = CheckRequest(
                case_id=case.id,
                phone=case.phone,
                requested_by_admin_id=admin_id,
                trigger=trigger,
                is_recheck=is_recheck,
            )
            session.add(request)

            # Qo'lda /check rejalashtirilgan avtomatik tekshiruvni bekor
            # qiladi (§6.1 b) — ikki marta tekshirilmasin.
            await self._close_jobs(session, case.id, (JobKind.CHECK_DUE,), now)

            if cached is not None and not is_recheck:
                # Keshdan javob — tekshiruvchiga yuborilmaydi.
                prev_status = case.status
                request.sent_at = now
                request.replied_at = now
                request.result = cached.result
                request.raw_reply = f"KESH (so'rov #{cached.id}): {cached.raw_reply}"
                case.status = (
                    CaseStatus.PASSED
                    if cached.result == CheckResult.PASSED
                    else CaseStatus.FAILED
                )
                await session.commit()
                await session.refresh(request)
                log.info(
                    "Case %s: kesh natijasi qo'llandi (%s).",
                    case.short_code or case.id,
                    cached.result.value,
                )
                if self.result_hook is not None:
                    await self.result_hook(request.id, prev_status)
                return f"Kesh: bu nomer yaqinda tekshirilgan — {cached.result.value}."

            case.status = CaseStatus.CHECK_QUEUED
            await session.commit()
            log.info(
                "Case %s tekshiruv navbatiga qo'yildi (%s, admin_id=%s).",
                case.short_code or case.id,
                trigger.value,
                admin_id,
            )
            return "So'rov navbatga qo'yildi."

    # ------------------------------------------------------------------ #
    # Drip — davriy chiqarish (6.2)
    # ------------------------------------------------------------------ #

    async def drip_tick(self) -> int:
        """Bitta tick: navbatdagi BARCHA mos so'rovlarni yuboradi.

        Foydalanuvchi qarori (2026-08-13): tezlik cheklovi OLIB TASHLANGAN —
        tekshiruvchi bir vaqtda istalgancha so'rov qabul qila oladi. "Drip"
        endi faqat davriy tekshiruv sikli (navbatga tushgan so'rov keyingi
        tick'da darhol ketadi), tomchilab-cheklash emas.

        Qaytaradi: shu tick'da yuborilgan so'rovlar soni.
        """
        async with self.session_factory() as session:
            if not await self._ready(session):
                return 0

            result = await session.execute(
                select(CheckRequest)
                .where(CheckRequest.sent_at.is_(None))
                .order_by(CheckRequest.queued_at, CheckRequest.id)
            )
            queued = result.scalars().all()
            if not queued:
                return 0

            sent_count = 0
            for request in queued:
                # §4.2b — nofaol adminning so'rovlari MUZLATILADI: navbatda
                # qoladi, yuborilmaydi (admin qaytsa davom etadi).
                admin = await session.get(Admin, request.requested_by_admin_id)
                if admin is not None and not admin.is_active:
                    continue

                template = await get_check_request_template(session)
                text = template.replace("{phone}", request.phone)

                msg_id = await self.send_to_checker(
                    request.requested_by_admin_id, text
                )
                if msg_id is None:
                    # B-6 — bir so'rov uchun bir marta alert (spam emas).
                    # Bitta adminning sessiyasi o'lik bo'lsa boshqalarning
                    # so'rovlari to'silmasin — continue.
                    if request.id not in self._send_failure_alerted:
                        self._send_failure_alerted.add(request.id)
                        await self.alert_sink(
                            f"⚠️ Tekshiruvchiga so'rov yuborilmadi (admin_id="
                            f"{request.requested_by_admin_id} sessiyasi "
                            f"ishlamayapti?). So'rov navbatda qoladi.",
                            True,
                        )
                    continue
                self._send_failure_alerted.discard(request.id)

                now = datetime.datetime.utcnow()
                request.sent_at = now
                request.sent_message_id = msg_id

                case = await session.get(Case, request.case_id)
                if case is not None:
                    case.status = CaseStatus.CHECK_SENT

                # §6.5 — javobsizlik nazorati (bazada, restart'dan omon).
                stall_minutes = await get_checker_stall_minutes(session)
                session.add(
                    ScheduledJob(
                        kind=JobKind.STALLED_ALERT,
                        case_id=request.case_id,
                        due_at=now + datetime.timedelta(minutes=stall_minutes),
                        payload=f'{{"request_id": {request.id}}}',
                    )
                )
                await session.commit()
                sent_count += 1
                log.info(
                    "So'rov #%s tekshiruvchiga yuborildi (%s, admin_id=%s).",
                    request.id,
                    request.phone,
                    request.requested_by_admin_id,
                )

            return sent_count

    # ------------------------------------------------------------------ #
    # Tekshiruvchi javobi (6.4)
    # ------------------------------------------------------------------ #

    async def handle_checker_reply(
        self, admin_id: int, text: str, reply_to_msg_id: int | None = None
    ) -> None:
        async with self.session_factory() as session:
            open_requests = await self._open_sent_requests_for_admin(session, admin_id)
            if not open_requests:
                return  # so'rov kutilmayapti — tekshiruvchining oddiy gapi

            request = self._bind_reply(open_requests, text, reply_to_msg_id)
            if request is None:
                await self.alert_sink(
                    f"⚠️ Tekshiruvchi javobini so'rovga bog'lab bo'lmadi "
                    f"(admin_id={admin_id}, ochiq so'rovlar: "
                    f"{len(open_requests)}): {text[:100]!r}",
                    True,
                )
                return

            patterns = await get_all_patterns(session)
            try:
                category = classify(text, patterns)
            except AmbiguousMatch:
                await self._finalize(
                    session,
                    request,
                    text,
                    CheckResult.UNRECOGNIZED,
                    CaseStatus.NEEDS_ADMIN,
                )
                await self.alert_sink(
                    f"⚠️ Tekshiruvchi javobi QARAMA-QARSHI tanildi "
                    f"(so'rov #{request.id}, {request.phone}): {text[:200]!r} — "
                    f"NEEDS_ADMIN.",
                    True,
                )
                return

            if category is None:
                # 6.4.5 — hali tanilmadi: KUTAMIZ (keyingi xabar kelishi
                # mumkin: "bir daqiqa..." kabi). Xom matn jurnalga yoziladi;
                # stall taymeri o'z ishini qiladi.
                request.raw_reply = (
                    f"{request.raw_reply}\n{text}".strip()
                    if request.raw_reply
                    else text
                )
                await session.commit()
                log.info(
                    "So'rov #%s: javob tanilmadi, kutilmoqda: %r",
                    request.id,
                    text[:100],
                )
                return

            result, case_status = _RESULT_BY_CATEGORY[category]
            await self._finalize(session, request, text, result, case_status)

            case = await session.get(Case, request.case_id)
            code = (case.short_code or case.id) if case else request.case_id
            if category == CheckCategory.CHECK_PASSED:
                await self.alert_sink(
                    f"✅ {code}: {request.phone} — ovoz O'TDI.", True
                )
            elif category == CheckCategory.CHECK_FAILED:
                await self.alert_sink(
                    f"❌ {code}: {request.phone} — ovoz O'TMADI.", True
                )
            else:
                await self.alert_sink(
                    f"⚠️ {code}: tekshiruvchi xato qaytardi ({text[:100]!r}) — "
                    f"NEEDS_ADMIN.",
                    True,
                )

    # ------------------------------------------------------------------ #
    # Stall (poller chaqiradi — STALLED_ALERT job)
    # ------------------------------------------------------------------ #

    async def handle_stalled(self, request_id: int) -> None:
        async with self.session_factory() as session:
            request = await session.get(CheckRequest, request_id)
            if request is None or request.replied_at is not None:
                return  # javob allaqachon kelgan — hammasi joyida

            case = await session.get(Case, request.case_id)
            if case is not None and case.status == CaseStatus.CHECK_SENT:
                case.status = CaseStatus.CHECK_STALLED

            # Umumiy manzara uchun barcha javobsiz so'rovlar soni.
            open_count = len(
                (
                    await session.execute(
                        select(CheckRequest.id).where(
                            CheckRequest.sent_at.is_not(None),
                            CheckRequest.replied_at.is_(None),
                        )
                    )
                ).all()
            )
            await session.commit()

            age = (
                datetime.datetime.utcnow() - request.sent_at
                if request.sent_at
                else datetime.timedelta(0)
            )
            age_min = int(age.total_seconds() // 60)

            # MUHIM farq: tekshiruvchi umuman JIMMI, yoki javob berdi-yu
            # tizim uni TANIMADIMI. Ikkovi butunlay boshqa muammo va
            # boshqa yechim talab qiladi, lekin avval ikkovi ham
            # "javob bermayapti" deb xabar qilinardi.
            #
            # Oqibati jonli tizimda ko'rindi: tekshiruvchi javob berib
            # turgan, shablonlar esa uni tanimagan — natijada 9 kun
            # davomida birorta ham natija chiqmagan va hech kim sababni
            # bilmagan, chunki alert "javob bermayapti" deb turgan.
            xom = (request.raw_reply or "").strip()
            if xom:
                await self.alert_sink(
                    f"❓ Tekshiruvchi JAVOB BERDI, lekin tizim uni TANIMADI "
                    f"({request.phone}, {age_min} daqiqa).\n\n"
                    f"Javob matni: <code>{xom[:300]}</code>\n\n"
                    f"Shu matnni tanish shabloniga qo'shing — shundan keyin "
                    f"bunday javoblar avtomatik ishlanadi:\n"
                    f"<code>/unrecognized</code> — ro'yxatdan tugma bilan, yoki\n"
                    f"<code>/testcheck {xom[:40]}</code> — avval sinab ko'ring.",
                    True,
                )
            else:
                await self.alert_sink(
                    f"⏳ Tekshiruvchi javob bermayapti: {request.phone} "
                    f"({age_min} daqiqa). Jami javobsiz: {open_count} ta. "
                    f"So'rov navbatda qoladi — mijozga hech narsa yozilmadi.",
                    True,
                )

        # B-4 — guruh postiga ⏳ reaksiya.
        if self.stalled_hook is not None:
            await self.stalled_hook(request_id)

    # ------------------------------------------------------------------ #
    # Ichki yordamchilar
    # ------------------------------------------------------------------ #

    async def _ready(self, session) -> bool:
        """6.4.7 — shablonlar to'liq va tekshiruvchi belgilangan bo'lishi shart."""
        missing = await missing_categories(session)
        checker = await get_checker_account(session)
        if not missing and checker is not None:
            self._not_ready_alerted = False
            return True
        if not self._not_ready_alerted:
            self._not_ready_alerted = True
            reasons = []
            if missing:
                reasons.append(
                    "tanish shablonlari to'liq emas: "
                    + ", ".join(c.value for c in missing)
                )
            if checker is None:
                reasons.append("tekshiruvchi akkaunt belgilanmagan (/setchecker)")
            await self.alert_sink(
                "⛔ Tekshiruv dvigateli ishga tushmadi — " + "; ".join(reasons) + ". "
                "So'rovlar navbatda kutmoqda.",
                True,
            )
        return False

    def _bind_reply(
        self,
        open_requests: list[CheckRequest],
        text: str,
        reply_to_msg_id: int | None,
    ) -> CheckRequest | None:
        """6.4.5 — reply > oxirgi 4 raqam > FIFO (eng eski ochiq so'rov).

        Tezlik cheklovi olib tashlangani uchun (2026-08-13) bir chatda bir
        nechta ochiq so'rov bo'lishi normal holat. Raqamsiz oddiy javob
        ("bor") ENG ESKI ochiq so'rovga bog'lanadi — tekshiruvchi tartib
        bilan javob beradi degan taxmin. Aniqlik kerak bo'lsa tekshiruvchi
        reply yoki oxirgi-4-raqam bilan yozadi (qo'llanmada tavsiya qilingan).
        """
        if reply_to_msg_id is not None:
            for r in open_requests:
                if r.sent_message_id == reply_to_msg_id:
                    return r

        runs = _DIGIT_RUN_RE.findall(text)
        if runs:
            matches = [
                r
                for r in open_requests
                if any(r.phone[-4:] == run[-4:] for run in runs)
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None  # bir xil oxirgi-4-raqamli IKKI so'rov — taxmin yo'q

        return open_requests[0] if open_requests else None

    async def _finalize(
        self,
        session,
        request: CheckRequest,
        text: str,
        result: CheckResult,
        case_status: CaseStatus,
    ) -> None:
        now = datetime.datetime.utcnow()
        request.replied_at = now
        request.result = result
        request.raw_reply = (
            f"{request.raw_reply}\n{text}".strip() if request.raw_reply else text
        )
        case = await session.get(Case, request.case_id)
        prev_status = case.status if case is not None else None
        if case is not None:
            case.status = case_status
        await self._close_jobs(
            session, request.case_id, (JobKind.STALLED_ALERT,), now
        )
        await session.commit()
        # B-4 — tarqatish (batch outcome, reaksiya, mijoz/tasdiqlash,
        # kech-javob to'g'irlash). prev_status kech javobni aniqlash uchun.
        if self.result_hook is not None:
            await self.result_hook(request.id, prev_status)

    async def _close_jobs(
        self, session, case_id: int, kinds: tuple[JobKind, ...], now: datetime.datetime
    ) -> None:
        result = await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.case_id == case_id,
                ScheduledJob.kind.in_(kinds),
                ScheduledJob.done_at.is_(None),
            )
        )
        for job in result.scalars().all():
            job.done_at = now

    async def _find_open_request_for_case(
        self, session, case_id: int
    ) -> CheckRequest | None:
        result = await session.execute(
            select(CheckRequest).where(
                CheckRequest.case_id == case_id,
                CheckRequest.replied_at.is_(None),
            )
        )
        return result.scalars().first()

    async def _find_recent_result(
        self, session, phone: str, since: datetime.datetime
    ) -> CheckRequest | None:
        result = await session.execute(
            select(CheckRequest)
            .where(
                CheckRequest.phone == phone,
                CheckRequest.result.in_([CheckResult.PASSED, CheckResult.FAILED]),
                CheckRequest.replied_at.is_not(None),
                CheckRequest.replied_at >= since,
            )
            .order_by(CheckRequest.replied_at.desc())
        )
        return result.scalars().first()

    async def _minutes_until_check_allowed(
        self, session, case_id: int, now: datetime.datetime
    ) -> int:
        """Tekshiruvga ruxsat berilgunicha necha daqiqa qolgani.

        0 — hozir mumkin. Anchor: case'ning OXIRGI rasm partiyasi (§6.1a —
        admin rasmni qayta tashlasa, hisob oxirgi rasmdan boshlanadi).

        Rasm umuman tashlanmagan bo'lsa 0 qaytariladi: bunday case'da
        cheklash mantiqsiz (kutiladigan rasm yo'q) va `/check` ni bloklash
        adminni ishlay olmaydigan holatga tushirardi.
        """
        oxirgi = (
            await session.execute(
                select(ScreenshotBatch.sent_at)
                .where(ScreenshotBatch.case_id == case_id)
                .order_by(ScreenshotBatch.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if oxirgi is None:
            return 0
        o_tgan = (now - oxirgi).total_seconds() / 60
        return max(0, int(round(MIN_CHECK_DELAY_MINUTES - o_tgan)))

    async def _admin_has_open_sent(self, session, admin_id: int) -> bool:
        result = await session.execute(
            select(CheckRequest.id).where(
                CheckRequest.requested_by_admin_id == admin_id,
                CheckRequest.sent_at.is_not(None),
                CheckRequest.replied_at.is_(None),
            )
        )
        return result.scalars().first() is not None

    async def _open_sent_requests_for_admin(
        self, session, admin_id: int
    ) -> list[CheckRequest]:
        result = await session.execute(
            select(CheckRequest)
            .where(
                CheckRequest.requested_by_admin_id == admin_id,
                CheckRequest.sent_at.is_not(None),
                CheckRequest.replied_at.is_(None),
            )
            .order_by(CheckRequest.sent_at, CheckRequest.id)
        )
        return list(result.scalars().all())
