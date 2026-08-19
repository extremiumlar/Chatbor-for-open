"""v2 statistika — TZ v2 8-bo'lim (B-5).

Barcha ko'rsatkichlar ADMIN KESIMIDA (TZ v2 8.2) — har hodisa qaysi admin
akkauntida sodir bo'lgani B-1 arxitekturasidan tabiiy chiqadi
(`cases.assigned_admin_id`, `screenshot_batches.admin_id`,
`check_requests.requested_by_admin_id`).

Vaqt chegaralari TOSHKENT (UTC+5) bo'yicha: "Bugun" = Toshkent yarim
kechasidan; bazadagi vaqtlar naive-UTC bo'lgani uchun chegaralar UTCga
o'girib so'raladi.
"""

import datetime
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import CaseStatus
from core.logic.admins import display_name
from core.logic.screenshots import TASHKENT_TZ
from core.models import (
    Admin,
    Case,
    CheckRequest,
    CheckResult,
    CheckTrigger,
    JobKind,
    OutcomeSource,
    ScheduledJob,
    ScreenshotBatch,
)


def tashkent_day_start_utc(now_utc: datetime.datetime, days_back: int = 0) -> datetime.datetime:
    """Toshkent bo'yicha kun boshi (00:00) — naive-UTC ko'rinishida."""
    local = now_utc.replace(tzinfo=datetime.timezone.utc).astimezone(TASHKENT_TZ)
    day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_local -= datetime.timedelta(days=days_back)
    return day_start_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def next_daily_report_due_utc(
    now_utc: datetime.datetime, time_str: str = "21:00"
) -> datetime.datetime:
    """Keyingi kunlik hisobot vaqti (Toshkent HH:MM) — naive-UTC."""
    try:
        hour, minute = (int(p) for p in time_str.strip().split(":"))
    except ValueError:
        hour, minute = 21, 0
    local = now_utc.replace(tzinfo=datetime.timezone.utc).astimezone(TASHKENT_TZ)
    due_local = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due_local <= local:
        due_local += datetime.timedelta(days=1)
    return due_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)


@dataclass
class AdminStatRow:
    admin_id: int | None
    admin_name: str
    cases: int = 0  # qabul qilingan nomerlar
    batches: int = 0  # rasm partiyalari (dublikatlarsiz)
    images: int = 0  # jami rasm
    duplicates: int = 0  # ⚠️ dublikat partiyalar
    checks_manual: int = 0  # /check bilan
    checks_auto: int = 0  # taymer bilan
    passed: int = 0
    failed: int = 0
    unknown: int = 0  # UNRECOGNIZED
    unreplied: int = 0  # yuborilgan, javob kutilmoqda (joriy holat)
    late_corrected: int = 0  # kech javob bilan to'g'irlangan
    overrides: int = 0  # guruhda qo'lda o'zgartirilgan reaksiya
    awaiting_screenshot: int = 0  # hali rasm tashlanmagan case'lar (joriy)
    # o'rtacha vaqtlar (daqiqa) — hisoblash uchun yig'indi/soni
    _number_to_batch_total: float = field(default=0.0, repr=False)
    _number_to_batch_count: int = field(default=0, repr=False)
    _reply_total: float = field(default=0.0, repr=False)
    _reply_count: int = field(default=0, repr=False)

    @property
    def checked(self) -> int:
        return self.passed + self.failed

    @property
    def conversion_pct(self) -> int | None:
        if self.checked == 0:
            return None
        return round(100 * self.passed / self.checked)

    @property
    def avg_number_to_batch_minutes(self) -> float | None:
        if self._number_to_batch_count == 0:
            return None
        return self._number_to_batch_total / self._number_to_batch_count

    @property
    def avg_reply_minutes(self) -> float | None:
        if self._reply_count == 0:
            return None
        return self._reply_total / self._reply_count


@dataclass
class StatsReport:
    since_utc: datetime.datetime
    rows: list[AdminStatRow]
    totals: AdminStatRow


async def gather_v2_stats(
    session: AsyncSession,
    since_utc: datetime.datetime,
    admin_id: int | None = None,
    until_utc: datetime.datetime | None = None,
    include_idle_admins: bool = True,
) -> StatsReport:
    """Davr statistikasi. `admin_id` berilsa faqat o'sha admin (TZ v2 8.4 —
    oddiy admin faqat o'zinikini ko'radi).

    `until_utc` — davr oxiri (berilmasa hozirgacha); oldingi davr bilan
    solishtirish uchun kerak.

    `include_idle_admins` — faoliyati NOL bo'lgan faol adminlar ham ro'yxatda
    ko'rinadi. Bu ataylab: "hodim bugun umuman ishlamadi" degan ma'lumot
    boshliq uchun eng qimmat signallardan biri, lekin qatorlar faqat hodisa
    kelganda yaratilsa, aynan shu hodimlar ro'yxatdan g'oyib bo'lib qolardi.
    """
    admins = {
        a.id: a for a in (await session.execute(select(Admin))).scalars().all()
    }
    rows: dict[int, AdminStatRow] = {}

    def row(aid: int | None) -> AdminStatRow:
        key = aid or 0
        if key not in rows:
            # `display_name` — "Ism Familiya (@username)"; seed paytidagi
            # xom tg_id emas, aks holda hisobotda kim kimligi bilinmaydi.
            name = display_name(admins[aid]) if aid in admins else f"#{aid}"
            rows[key] = AdminStatRow(admin_id=aid, admin_name=name)
        return rows[key]

    def wanted(aid: int | None) -> bool:
        return admin_id is None or aid == admin_id

    def in_window(ts: datetime.datetime | None) -> bool:
        if ts is None:
            return False
        return until_utc is None or ts < until_utc

    # Faol adminlarning bo'sh qatorlari — nol faoliyat ham ko'rinsin.
    if include_idle_admins:
        for aid, a in admins.items():
            if a.is_active and wanted(aid):
                row(aid)

    # --- nomerlar (cases) ---
    stmt = select(Case).where(Case.created_at >= since_utc)
    if until_utc is not None:
        stmt = stmt.where(Case.created_at < until_utc)
    result = await session.execute(stmt)
    case_created_at: dict[int, datetime.datetime] = {}
    for case in result.scalars().all():
        case_created_at[case.id] = case.created_at
        if not wanted(case.assigned_admin_id):
            continue
        r = row(case.assigned_admin_id)
        r.cases += 1

    # --- joriy "rasm kutilmoqda" (davrga bog'lanmagan holat surati) ---
    result = await session.execute(
        select(Case).where(Case.status == CaseStatus.NUMBER_RECEIVED)
    )
    for case in result.scalars().all():
        if wanted(case.assigned_admin_id):
            row(case.assigned_admin_id).awaiting_screenshot += 1

    # --- rasm partiyalari ---
    stmt = select(ScreenshotBatch).where(ScreenshotBatch.sent_at >= since_utc)
    if until_utc is not None:
        stmt = stmt.where(ScreenshotBatch.sent_at < until_utc)
    result = await session.execute(stmt)
    for batch in result.scalars().all():
        if not wanted(batch.admin_id):
            continue
        r = row(batch.admin_id)
        if batch.is_duplicate:
            r.duplicates += 1
        else:
            r.batches += 1
            r.images += batch.image_count
        if batch.outcome_source == OutcomeSource.MANUAL:
            r.overrides += 1
        created = case_created_at.get(batch.case_id)
        if created is None:
            case_obj = await session.get(Case, batch.case_id)
            created = case_obj.created_at if case_obj else None
        if created is not None and batch.sent_at is not None:
            delta_min = (batch.sent_at - created).total_seconds() / 60
            if delta_min >= 0:
                r._number_to_batch_total += delta_min
                r._number_to_batch_count += 1

    # --- tekshiruv so'rovlari ---
    stmt = select(CheckRequest).where(CheckRequest.queued_at >= since_utc)
    if until_utc is not None:
        stmt = stmt.where(CheckRequest.queued_at < until_utc)
    result = await session.execute(stmt)
    for req in result.scalars().all():
        if not wanted(req.requested_by_admin_id):
            continue
        r = row(req.requested_by_admin_id)
        if req.trigger == CheckTrigger.MANUAL:
            r.checks_manual += 1
        else:
            r.checks_auto += 1
        if req.result == CheckResult.PASSED:
            r.passed += 1
        elif req.result == CheckResult.FAILED:
            r.failed += 1
        elif req.result == CheckResult.UNRECOGNIZED:
            r.unknown += 1
        if req.sent_at is not None and req.replied_at is None:
            r.unreplied += 1
        if req.late_corrected:
            r.late_corrected += 1
        if req.sent_at is not None and req.replied_at is not None:
            delta_min = (req.replied_at - req.sent_at).total_seconds() / 60
            if delta_min >= 0:
                r._reply_total += delta_min
                r._reply_count += 1

    ordered = sorted(rows.values(), key=lambda r: -r.cases)

    totals = AdminStatRow(admin_id=None, admin_name="Jami")
    for r in ordered:
        totals.cases += r.cases
        totals.batches += r.batches
        totals.images += r.images
        totals.duplicates += r.duplicates
        totals.checks_manual += r.checks_manual
        totals.checks_auto += r.checks_auto
        totals.passed += r.passed
        totals.failed += r.failed
        totals.unknown += r.unknown
        totals.unreplied += r.unreplied
        totals.late_corrected += r.late_corrected
        totals.overrides += r.overrides
        totals.awaiting_screenshot += r.awaiting_screenshot
        totals._number_to_batch_total += r._number_to_batch_total
        totals._number_to_batch_count += r._number_to_batch_count
        totals._reply_total += r._reply_total
        totals._reply_count += r._reply_count

    return StatsReport(since_utc=since_utc, rows=ordered, totals=totals)


# --------------------------------------------------------------------------- #
# Render (adminbot HTML va guruh matni)
# --------------------------------------------------------------------------- #


def _fmt_avg(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 60:
        return f"{value / 60:.1f} soat"
    return f"{value:.0f} daq"


def _admin_line(r: AdminStatRow) -> str:
    conv = f"{r.conversion_pct}%" if r.conversion_pct is not None else "—"
    extra = []
    if r.awaiting_screenshot:
        extra.append(f"⚠️ {r.awaiting_screenshot} rasmsiz")
    if r.duplicates:
        extra.append(f"{r.duplicates} dublikat")
    extra_text = ("  " + " · ".join(extra)) if extra else ""
    return (
        f"{r.admin_name}: {r.cases} nomer · {r.batches} partiya · "
        f"{r.checked} tekshirildi · ✅{r.passed}/❌{r.failed} ({conv}){extra_text}"
    )


def render_stats(report: StatsReport, title: str) -> str:
    """Adminbot uchun (HTML)."""
    t = report.totals
    conv = f"{t.conversion_pct}%" if t.conversion_pct is not None else "—"
    lines = [
        f"📊 <b>{title}</b>",
        "",
        f"Nomerlar: <b>{t.cases}</b> · Partiyalar: <b>{t.batches}</b> "
        f"(rasm: {t.images}, dublikat: {t.duplicates})",
        f"Tekshiruv: qo'lda {t.checks_manual} · avto {t.checks_auto}",
        f"✅ O'tdi: <b>{t.passed}</b> · ❌ O'tmadi: <b>{t.failed}</b> · "
        f"⚠️ Noaniq: {t.unknown} · ⏳ Javobsiz: {t.unreplied}",
        f"Konversiya: <b>{conv}</b>",
        f"O'rtacha nomer→rasm: {_fmt_avg(t.avg_number_to_batch_minutes)} · "
        f"so'rov→javob: {_fmt_avg(t.avg_reply_minutes)}",
    ]
    if t.late_corrected or t.overrides:
        lines.append(
            f"Kech to'g'irlangan: {t.late_corrected} · Qo'lda override: {t.overrides}"
        )
    if t.awaiting_screenshot:
        lines.append(f"⚠️ Rasm kutilmoqda: {t.awaiting_screenshot}")
    if len(report.rows) > 1:
        lines.append("")
        for r in report.rows:
            lines.append(_admin_line(r))
    return "\n".join(lines)


def render_daily_group_report(report: StatsReport, date_str: str) -> str:
    """Nazorat guruhiga kunlik xulosa — TZ v2 8.3 formati."""
    t = report.totals
    lines = [
        f"📊 {date_str} yakuni",
        "",
        f"Jami: {t.cases} nomer · {t.batches} partiya · {t.checked} tekshiruv",
        f"✅ {t.passed} o'tdi   ❌ {t.failed} o'tmadi   "
        f"⚠️ {t.unknown} noaniq   ⏳ {t.unreplied} javobsiz",
    ]
    if report.rows:
        lines.append("")
        for r in report.rows:
            lines.append(_admin_line(r))
    return "\n".join(lines)


def render_daily_superadmin_report(report: StatsReport, date_str: str) -> str:
    """Superadmin lichkasiga batafsilroq nusxa — TZ v2 8.1."""
    t = report.totals
    base = render_daily_group_report(report, date_str)
    extra = [
        "",
        "— Superadmin qo'shimchasi —",
        f"Dublikat partiyalar: {t.duplicates}",
        f"Kech to'g'irlangan natijalar: {t.late_corrected}",
        f"Qo'lda o'zgartirilgan reaksiyalar (override): {t.overrides}",
        f"Hozir rasm kutayotgan case'lar: {t.awaiting_screenshot}",
        f"Hozir javobsiz so'rovlar: {t.unreplied}",
        f"O'rtacha nomer→rasm: {_fmt_avg(t.avg_number_to_batch_minutes)} · "
        f"so'rov→javob: {_fmt_avg(t.avg_reply_minutes)}",
    ]
    return base + "\n" + "\n".join(extra)


# --------------------------------------------------------------------------- #
# Solishtirish, reyting va hodim kartochkasi
# --------------------------------------------------------------------------- #


@dataclass
class ComparisonReport:
    """Joriy davr + xuddi shunday uzunlikdagi OLDINGI davr."""

    current: StatsReport
    previous: StatsReport


async def gather_with_comparison(
    session: AsyncSession,
    since_utc: datetime.datetime,
    admin_id: int | None = None,
) -> ComparisonReport:
    """Joriy davrni va undan bevosita oldingi teng davrni birga yig'adi.

    Masalan "Hafta" tanlansa: joriy 7 kun va undan avvalgi 7 kun — o'sish/
    pasayish foizini ko'rsatish uchun.
    """
    now = datetime.datetime.utcnow()
    span = now - since_utc
    prev_since = since_utc - span

    current = await gather_v2_stats(session, since_utc, admin_id=admin_id)
    previous = await gather_v2_stats(
        session, prev_since, admin_id=admin_id, until_utc=since_utc,
        include_idle_admins=False,
    )
    return ComparisonReport(current=current, previous=previous)


def trend(current: int, previous: int) -> str:
    """O'sish/pasayish belgisi: 12 → 8 uchun "↗️ +50%" kabi."""
    if previous == 0:
        return "🆕" if current > 0 else "—"
    pct = round(100 * (current - previous) / previous)
    if pct > 0:
        return f"↗️ +{pct}%"
    if pct < 0:
        return f"↘️ {pct}%"
    return "→ 0%"


def leaderboard(report: StatsReport) -> list[AdminStatRow]:
    """Reyting: tasdiqlangan soni, keyin konversiya bo'yicha.

    Faqat haqiqiy adminlarga tegishli qatorlar (admin_id=None — "biriktirilmagan"
    qatori reytingga kirmaydi, u odam emas).
    """
    real = [r for r in report.rows if r.admin_id is not None]
    return sorted(real, key=lambda r: (-r.passed, -(r.conversion_pct or 0), -r.cases))


_MEDALS = ["🥇", "🥈", "🥉"]


def render_leaderboard(report: StatsReport, title: str) -> str:
    rows = leaderboard(report)
    lines = [f"🏆 <b>{title}</b>", ""]
    if not rows or all(r.cases == 0 and r.checked == 0 for r in rows):
        lines.append("<i>Bu davrda faoliyat bo'lmadi.</i>")
        return "\n".join(lines)

    for i, r in enumerate(rows):
        medal = _MEDALS[i] if i < len(_MEDALS) else f"{i + 1}."
        conv = f"{r.conversion_pct}%" if r.conversion_pct is not None else "—"
        lines.append(
            f"{medal} <b>{r.admin_name}</b> — ✅{r.passed} tasdiq · "
            f"{r.cases} nomer · konversiya {conv}"
        )
        if r.cases == 0 and r.checked == 0:
            lines[-1] = f"{medal} <b>{r.admin_name}</b> — 💤 faoliyat yo'q"
    return "\n".join(lines)


def render_comparison(cmp: ComparisonReport, title: str) -> str:
    """Umumiy ko'rinish + oldingi davr bilan solishtirish."""
    t, p = cmp.current.totals, cmp.previous.totals
    conv = f"{t.conversion_pct}%" if t.conversion_pct is not None else "—"
    lines = [
        f"📊 <b>{title}</b>  <i>(oldingi davrga nisbatan)</i>",
        "",
        f"Nomerlar: <b>{t.cases}</b>  {trend(t.cases, p.cases)}",
        f"Partiyalar: <b>{t.batches}</b>  {trend(t.batches, p.batches)} "
        f"(rasm: {t.images}, dublikat: {t.duplicates})",
        f"Tekshiruv: <b>{t.checked}</b>  {trend(t.checked, p.checked)} "
        f"(qo'lda {t.checks_manual} · avto {t.checks_auto})",
        f"✅ O'tdi: <b>{t.passed}</b>  {trend(t.passed, p.passed)}",
        f"❌ O'tmadi: <b>{t.failed}</b>  {trend(t.failed, p.failed)}",
        f"Konversiya: <b>{conv}</b>",
        f"O'rtacha nomer→rasm: {_fmt_avg(t.avg_number_to_batch_minutes)} · "
        f"so'rov→javob: {_fmt_avg(t.avg_reply_minutes)}",
    ]
    if t.unknown or t.unreplied or t.awaiting_screenshot:
        lines.append(
            f"⚠️ Noaniq: {t.unknown} · ⏳ Javobsiz: {t.unreplied} · "
            f"📷 Rasm kutilmoqda: {t.awaiting_screenshot}"
        )
    return "\n".join(lines)


def render_admin_detail(
    row: AdminStatRow, prev_row: AdminStatRow | None, title: str
) -> str:
    """Bitta hodimning batafsil kartochkasi."""
    conv = f"{row.conversion_pct}%" if row.conversion_pct is not None else "—"

    def tr(cur: int, attr: str) -> str:
        return trend(cur, getattr(prev_row, attr)) if prev_row is not None else ""

    lines = [
        f"👤 <b>{row.admin_name}</b> — {title}",
        "",
        f"Qabul qilingan nomerlar: <b>{row.cases}</b>  {tr(row.cases, 'cases')}",
        f"Rasm partiyalari: <b>{row.batches}</b> (jami {row.images} rasm)  "
        f"{tr(row.batches, 'batches')}",
        f"Tekshiruvlar: <b>{row.checked}</b> (qo'lda {row.checks_manual} · "
        f"avto {row.checks_auto})",
        f"✅ O'tdi: <b>{row.passed}</b>  {tr(row.passed, 'passed')}",
        f"❌ O'tmadi: <b>{row.failed}</b>  {tr(row.failed, 'failed')}",
        f"Konversiya: <b>{conv}</b>",
        "",
        f"⏱ O'rtacha nomer→rasm: {_fmt_avg(row.avg_number_to_batch_minutes)}",
        f"⏱ O'rtacha so'rov→javob: {_fmt_avg(row.avg_reply_minutes)}",
    ]
    issues = []
    if row.awaiting_screenshot:
        issues.append(f"📷 rasm kutilmoqda: {row.awaiting_screenshot}")
    if row.unreplied:
        issues.append(f"⏳ javobsiz: {row.unreplied}")
    if row.duplicates:
        issues.append(f"♻️ dublikat: {row.duplicates}")
    if row.unknown:
        issues.append(f"⚠️ noaniq: {row.unknown}")
    if row.late_corrected:
        issues.append(f"🕰 kech to'g'irlangan: {row.late_corrected}")
    if row.overrides:
        issues.append(f"✍️ qo'lda override: {row.overrides}")
    if issues:
        lines += ["", "<b>E'tibor kerak:</b>", "  " + "\n  ".join(issues)]
    if row.cases == 0 and row.checked == 0 and row.batches == 0:
        lines += ["", "💤 <i>Bu davrda faoliyat qayd etilmagan.</i>"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Kunlik hisobotni rejalash (DAILY_REPORT job)
# --------------------------------------------------------------------------- #


async def ensure_daily_report_scheduled(
    session: AsyncSession, time_str: str = "21:00"
) -> None:
    """Ochiq DAILY_REPORT ishi bo'lmasa, keyingisini yaratadi (idempotent —
    startup'da chaqiriladi; poller har bajarilganda keyingisini o'zi yozadi)."""
    result = await session.execute(
        select(ScheduledJob.id).where(
            ScheduledJob.kind == JobKind.DAILY_REPORT,
            ScheduledJob.done_at.is_(None),
        )
    )
    if result.scalars().first() is not None:
        return
    session.add(
        ScheduledJob(
            kind=JobKind.DAILY_REPORT,
            due_at=next_daily_report_due_utc(datetime.datetime.utcnow(), time_str),
        )
    )
    await session.commit()
