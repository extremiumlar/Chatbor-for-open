"""`scheduled_jobs` polleri — TZ v2 9.4 (B-3).

Har N soniyada muddati kelgan ishlarni oladi va turiga qarab bajaradi.
Taymerlar bazada bo'lgani uchun restart hech narsani yo'qotmaydi: jarayon
qayta ko'tarilganda muddati o'tib ketgan ishlar birinchi tick'da bajariladi.

Xato bo'lsa ish YO'QOLMAYDI: `attempts` oshiriladi va qayta urinish uchun
kechiktiriladi; limitdan oshsa yopilib superadminga alert beriladi.
"""

import asyncio
import datetime
import json
import logging
from contextlib import AbstractAsyncContextManager
from typing import Awaitable, Callable

from sqlalchemy import select

from core.enums import CaseStatus
from core.logic.check_engine import CheckEngine
from core.logic.screenshots import format_phone_pretty
from core.logic.settings_store import (
    get_daily_report_time,
    get_no_screenshot_first_minutes,
    get_no_screenshot_reminders,
)
from core.logic.v2_stats import next_daily_report_due_utc
from core.models import Admin, Case, CheckTrigger, JobKind, ScheduledJob, User

log = logging.getLogger("job_poller")

AlertSink = Callable[[str, bool], Awaitable[None]]

_MAX_ATTEMPTS = 5
_RETRY_DELAY_SECONDS = 60


class JobPoller:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager],
        engine: CheckEngine,
        alert_sink: AlertSink,
        poll_seconds: float = 30.0,
        distributor=None,
        daily_report: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.engine = engine
        self.alert_sink = alert_sink
        self.poll_seconds = poll_seconds
        # B-4 — ResultDistributor: NOTIFY_FAILED ishlarini bajaradi (adminbot
        # tugma bosilganda job yozadi, mijozga yozishni Teleton qiladi).
        self.distributor = distributor
        # B-5 — kunlik hisobot hook'i (relay beradi: guruh + superadmin).
        self.daily_report = daily_report

    async def run_loop(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                await self.tick()
            except Exception as exc:
                log.exception("Poller tick'ida kutilmagan xato")
                await self.alert_sink(f"KRITIK: poller xatosi: {exc!r}", True)

    async def tick(self) -> int:
        """Muddati kelgan barcha ishlarni bajaradi. Qaytaradi: bajarilgan soni."""
        now = datetime.datetime.utcnow()
        async with self.session_factory() as session:
            result = await session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.done_at.is_(None), ScheduledJob.due_at <= now)
                .order_by(ScheduledJob.due_at, ScheduledJob.id)
            )
            due_jobs = result.scalars().all()
            job_ids = [j.id for j in due_jobs]

        done = 0
        for job_id in job_ids:
            if await self._run_one(job_id):
                done += 1
        return done

    async def _run_one(self, job_id: int) -> bool:
        async with self.session_factory() as session:
            job = await session.get(ScheduledJob, job_id)
            if job is None or job.done_at is not None:
                return False
            kind = job.kind
            case_id = job.case_id
            payload = job.payload

        try:
            if kind == JobKind.CHECK_DUE:
                await self._handle_check_due(case_id)
            elif kind == JobKind.REMIND_NO_SCREENSHOT:
                await self._handle_remind(job_id, case_id, payload)
            elif kind == JobKind.STALLED_ALERT:
                request_id = json.loads(payload or "{}").get("request_id")
                if request_id is not None:
                    await self.engine.handle_stalled(int(request_id))
            elif kind == JobKind.NOTIFY_FAILED:
                request_id = json.loads(payload or "{}").get("request_id")
                if request_id is not None and self.distributor is not None:
                    await self.distributor.send_failed_now(int(request_id))
            elif kind == JobKind.DAILY_REPORT:
                if self.daily_report is not None:
                    await self.daily_report()
                # Keyingi kunga qayta rejalash — hisobot zanjiri uzilmasin.
                async with self.session_factory() as session:
                    time_str = await get_daily_report_time(session)
                    session.add(
                        ScheduledJob(
                            kind=JobKind.DAILY_REPORT,
                            due_at=next_daily_report_due_utc(
                                datetime.datetime.utcnow(), time_str
                            ),
                        )
                    )
                    await session.commit()
            else:
                log.warning("Noma'lum job turi #%s: %s", job_id, kind)
        except Exception as exc:
            log.exception("Job #%s bajarilmadi (%s)", job_id, kind)
            await self._register_failure(job_id, exc)
            return False

        await self._mark_done(job_id)
        return True

    # ------------------------------------------------------------------ #
    # Ish turlari
    # ------------------------------------------------------------------ #

    async def _handle_check_due(self, case_id: int | None) -> None:
        """§6.1 a — rasm vaqti + 90daq: tekshiruvni avtomatik boshlash."""
        if case_id is None:
            return
        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            admin = (
                await session.get(Admin, case.assigned_admin_id)
                if case is not None and case.assigned_admin_id is not None
                else None
            )
        if case is None or case.status != CaseStatus.SCREENSHOTS_SENT:
            # Boshqa holat: /check allaqachon boshlagan (CHECK_QUEUED+),
            # yoki case yopilgan — ish jimgina yopiladi.
            return
        if admin is not None and not admin.is_active:
            # §4.2b — nofaol admin: case muzlatilgan, tekshiruv boshlanmaydi.
            # Job yopiladi; admin faollashtirilganda rasm qayta tashlansa yoki
            # /check qilinsa oqim davom etadi.
            return
        await self.engine.request_check(case_id, CheckTrigger.AUTO)

    async def _handle_remind(
        self, job_id: int, case_id: int | None, payload: str
    ) -> None:
        """§6.1 a2 — rasmsizlik eslatmasi (kupon holatiga qarab 2 xil matn)."""
        if case_id is None:
            return
        async with self.session_factory() as session:
            case = await session.get(Case, case_id)
            if case is None or case.status != CaseStatus.NUMBER_RECEIVED:
                return  # rasm tashlangan yoki case boshqa yo'lda — eslatma kerak emas

            user = await session.get(User, case.user_id)
            admin = (
                await session.get(Admin, case.assigned_admin_id)
                if case.assigned_admin_id is not None
                else None
            )
            if admin is not None and not admin.is_active:
                # §4.2b — nofaol admin: eslatmalar ham muzlatiladi.
                return
            reminder_no = int(json.loads(payload or "{}").get("reminder_no", 1))
            limit = await get_no_screenshot_reminders(session)
            interval = await get_no_screenshot_first_minutes(session)

            admin_name = admin.name if admin else "?"
            customer = (
                f"@{user.tg_username}" if user and user.tg_username else ""
            ) or (user.display_name if user else "") or "mijoz"
            phone = format_phone_pretty(case.phone)

            if case.coupon is not None:
                # Kupon bor = mijoz allaqachon ovoz bergan.
                text = (
                    f"⚠️ {admin_name}: {customer} ({phone}) kupon raqamini "
                    f"yubordi — siz rasm tashlashni unutdingiz. "
                    f"({reminder_no}/{limit}-eslatma)"
                )
            else:
                # Kupon yo'q = mijoz hali ovoz bermagan.
                text = (
                    f"⚠️ {admin_name}: {customer} ({phone}) nomer yubordi — "
                    f"uning ovozini ham olib qo'ying. "
                    f"({reminder_no}/{limit}-eslatma)"
                )
            await self.alert_sink(text, True)

            if reminder_no < limit:
                session.add(
                    ScheduledJob(
                        kind=JobKind.REMIND_NO_SCREENSHOT,
                        case_id=case.id,
                        due_at=datetime.datetime.utcnow()
                        + datetime.timedelta(minutes=interval),
                        payload=json.dumps({"reminder_no": reminder_no + 1}),
                    )
                )
                await session.commit()
            else:
                # §6.1 a2 — eslatmalar tugadi: superadminga o'tadi, case
                # OCHIQ qoladi (yopilmaydi), statistikada "tashlab ketilgan".
                coupon_note = (
                    "Kupon: bor (mijoz ovoz bergan)."
                    if case.coupon is not None
                    else "Kupon: yo'q (mijoz hali ovoz bermagan)."
                )
                await self.alert_sink(
                    f"🔴 {admin_name} {limit} ta eslatmaga javob bermadi — "
                    f"{customer} ({phone}), {case.short_code or case.id}. "
                    f"{coupon_note} Case ochiq qoladi — qaror superadminda.",
                    True,
                )

    # ------------------------------------------------------------------ #
    # Ish holati
    # ------------------------------------------------------------------ #

    async def _mark_done(self, job_id: int) -> None:
        async with self.session_factory() as session:
            job = await session.get(ScheduledJob, job_id)
            if job is not None and job.done_at is None:
                job.done_at = datetime.datetime.utcnow()
                await session.commit()

    async def _register_failure(self, job_id: int, exc: Exception) -> None:
        async with self.session_factory() as session:
            job = await session.get(ScheduledJob, job_id)
            if job is None:
                return
            job.attempts += 1
            if job.attempts >= _MAX_ATTEMPTS:
                job.done_at = datetime.datetime.utcnow()
                await session.commit()
                await self.alert_sink(
                    f"KRITIK: job #{job_id} ({job.kind.value}) {job.attempts} "
                    f"urinishdan keyin ham bajarilmadi, yopildi: {exc!r}",
                    True,
                )
            else:
                job.due_at = datetime.datetime.utcnow() + datetime.timedelta(
                    seconds=_RETRY_DELAY_SECONDS
                )
                await session.commit()
