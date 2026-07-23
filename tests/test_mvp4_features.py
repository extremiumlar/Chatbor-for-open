"""MVP-4: statistika, audit_log, restart reconciliation, kunlik backup."""

import os
import sqlite3

from core.enums import CaseStatus
from core.logic.audit import list_recent, log_action
from core.logic.backup import _prune_old_backups, backup_once
from core.logic.reconciliation import reconcile_after_restart
from core.logic.stats import gather_stats
from tests.test_case_state_machine import _bot_busy_count, _latest_case


# --------------------------------------------------------------------------- #
# Audit log (TZ 11.5, 12.2)
# --------------------------------------------------------------------------- #


async def test_log_action_and_list_recent_order(session_factory):
    async with session_factory() as session:
        await log_action(session, 111, "addbot", "@testbot")
        await log_action(session, 111, "settemplate", "KEY -> value")

        entries = await list_recent(session, limit=10)

    assert len(entries) == 2
    assert entries[0].action == "settemplate"  # eng oxirgisi birinchi
    assert entries[1].action == "addbot"


async def test_list_recent_respects_limit(session_factory):
    async with session_factory() as session:
        for i in range(5):
            await log_action(session, 111, f"action{i}")

        entries = await list_recent(session, limit=3)

    assert len(entries) == 3


# --------------------------------------------------------------------------- #
# Statistika (TZ 10-bo'lim)
# --------------------------------------------------------------------------- #


async def test_gather_stats_counts_by_status_today_and_problems(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()

    await cm.handle_phone_detected(901, "u1", "U1", "998901111111")
    await cm.handle_coupon_received(901, "111111")  # CONFIRMED

    await cm.handle_phone_detected(902, "u2", "U2", "998902222222")
    await cm.handle_coupon_received(902, "333333")  # REJECTED

    await cm.handle_phone_detected(901, "u1", "U1", "998901111111")  # ALREADY_CONFIRMED, case ochilmaydi

    async with session_factory() as session:
        stats = await gather_stats(session)

    assert stats.today_count == 2  # faqat haqiqiy 2 ta case ochildi
    assert stats.by_status.get("CONFIRMED") == 1
    assert stats.by_status.get("REJECTED") == 1
    assert stats.problem_count == 0


async def test_gather_stats_counts_problem_statuses(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1", "bot2"])
    cm = make_case_manager()

    await cm.handle_phone_detected(911, "u3", "U3", "998903333333")
    await cm.handle_phone_detected(911, "u3", "U3", "998904444444")  # DUPLICATE_ACTIVE

    async with session_factory() as session:
        stats = await gather_stats(session)

    assert stats.problem_count == 1
    assert stats.by_status.get("DUPLICATE_ACTIVE") == 1


# --------------------------------------------------------------------------- #
# Restart reconciliation (TZ 12-bo'lim, Q37)
# --------------------------------------------------------------------------- #


async def test_reconciliation_moves_stuck_case_to_needs_admin_and_releases_bot(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    await cm.handle_phone_detected(1001, "u4", "U4", "998905555555")
    case = await _latest_case(session_factory, 1001)
    assert case.status == CaseStatus.AWAITING_COUPON
    assert await _bot_busy_count(session_factory) == 1

    alerts = []

    async def capture_alert(message, important=True):
        alerts.append((message, important))

    async def capture_notify(tg_user_id, text):
        pass

    await reconcile_after_restart(cm, session_factory, capture_alert, capture_notify)

    reconciled = await _latest_case(session_factory, 1001)
    assert reconciled.status == CaseStatus.NEEDS_ADMIN
    assert await _bot_busy_count(session_factory) == 0
    assert any("RESTART" in m and important for m, important in alerts)


async def test_reconciliation_redispatches_queued_case_after_true_restart(
    seed_bots, make_case_manager, session_factory
):
    await seed_bots(["bot1"])
    cm_before_crash = make_case_manager()

    await cm_before_crash.handle_phone_detected(1011, "u5", "U5", "998906666666")
    outcome2 = await cm_before_crash.handle_phone_detected(1012, "u6", "U6", "998907777777")
    assert outcome2.customer_text is None  # navbatga tushdi (DB'da NUMBER_RECEIVED)

    case1 = await _latest_case(session_factory, 1011)
    assert case1.status == CaseStatus.AWAITING_COUPON
    case2 = await _latest_case(session_factory, 1012)
    assert case2.status == CaseStatus.NUMBER_RECEIVED

    # "Restart" simulyatsiyasi — YANGI CaseManager (bo'sh navbat, timer yo'q)
    # xuddi shu bazaga ulanadi, xuddi jarayon qayta ishga tushgandek.
    cm_after_restart = make_case_manager()

    notified = []

    async def capture_notify(tg_user_id, text):
        notified.append((tg_user_id, text))

    async def capture_alert(message, important=True):
        pass

    await reconcile_after_restart(cm_after_restart, session_factory, capture_alert, capture_notify)

    case1_after = await _latest_case(session_factory, 1011)
    assert case1_after.status == CaseStatus.NEEDS_ADMIN  # yarim qolgan edi

    case2_after = await _latest_case(session_factory, 1012)
    assert case2_after.status == CaseStatus.AWAITING_COUPON  # navbatdagi -> qayta dispatch
    assert case2_after.bot_id is not None
    assert any(tg_id == 1012 for tg_id, _ in notified)


async def test_reconciliation_is_noop_when_nothing_stuck(seed_bots, make_case_manager, session_factory):
    await seed_bots(["bot1"])
    cm = make_case_manager()

    alerts = []

    async def capture_alert(message, important=True):
        alerts.append((message, important))

    async def capture_notify(tg_user_id, text):
        pass

    await reconcile_after_restart(cm, session_factory, capture_alert, capture_notify)
    assert alerts == []


# --------------------------------------------------------------------------- #
# Kunlik SQLite backup (TZ 13-bo'lim, Q60)
# --------------------------------------------------------------------------- #


def test_prune_old_backups_keeps_only_newest_n(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(5):
        (backup_dir / f"backup_{i:04d}.db").write_text("x")

    _prune_old_backups(str(backup_dir), retention=2)

    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert remaining == ["backup_0003.db", "backup_0004.db"]


async def test_backup_once_creates_restorable_copy(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO t (val) VALUES ('hello')")
    conn.commit()
    conn.close()

    database_url = f"sqlite+aiosqlite:///{db_path}"
    dest = await backup_once(database_url, str(tmp_path / "backups"), retention=5)

    assert dest is not None
    assert os.path.exists(dest)

    check_conn = sqlite3.connect(dest)
    rows = check_conn.execute("SELECT val FROM t").fetchall()
    check_conn.close()
    assert rows == [("hello",)]


async def test_backup_once_returns_none_for_non_sqlite_url(tmp_path):
    dest = await backup_once("postgresql://user:pass@host/db", str(tmp_path / "backups"), retention=5)
    assert dest is None
