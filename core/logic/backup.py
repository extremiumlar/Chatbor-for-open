"""Kunlik avtomatik SQLite backup — TZ 13-bo'lim (Q60 — TASDIQLANGAN)."""

import asyncio
import glob
import logging
import os
import sqlite3
import datetime
from typing import Awaitable, Callable

from core.db import sqlite_file_path

log = logging.getLogger("backup")


def _sync_backup(db_path: str, dest_path: str) -> None:
    """sqlite3'ning o'z `.backup()` APIsi — fayl nusxalashdan farqli
    o'laroq, baza yozish jarayonida bo'lsa ham izchil (atomik) nusxa oladi."""
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _prune_old_backups(backup_dir: str, retention: int) -> None:
    files = sorted(glob.glob(os.path.join(backup_dir, "backup_*.db")))
    for old_file in files[: max(0, len(files) - retention)]:
        os.remove(old_file)


async def backup_once(database_url: str, backup_dir: str, retention: int = 14) -> str | None:
    """Bitta backup yaratadi, yaratilgan fayl yo'lini qaytaradi.

    SQLite bo'lmagan DATABASE_URL uchun (kelajakda PostgreSQL) None
    qaytaradi va log'ga yozadi — bu holatda alohida backup yechimi kerak.
    """
    db_path = sqlite_file_path(database_url)
    if db_path is None:
        log.warning("Backup faqat SQLite uchun ishlaydi, DATABASE_URL mos kelmadi: %s", database_url)
        return None

    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"backup_{stamp}.db")

    await asyncio.to_thread(_sync_backup, db_path, dest)
    await asyncio.to_thread(_prune_old_backups, backup_dir, retention)
    return dest


async def daily_backup_loop(
    database_url: str,
    backup_dir: str,
    interval_seconds: float,
    retention: int = 14,
    alert_sink: Callable[[str, bool], Awaitable[None]] | None = None,
) -> None:
    """Audit J-5 — `alert_sink` ixtiyoriy (`None` — chaqiruvchi bermasa,
    avvalgidek faqat log yoziladi): berilsa, TZ 12.1 (Q42) talab qilganidek
    kritik xato adminbotga ham darhol push qilinadi, faqat faylga emas."""
    while True:
        try:
            dest = await backup_once(database_url, backup_dir, retention)
            if dest is not None:
                log.info("Kunlik backup yaratildi: %s", dest)
        except Exception as exc:
            log.exception("Backup yaratishda xato")
            if alert_sink is not None:
                await alert_sink(f"KRITIK: kunlik backup yaratishda xato: {exc!r}", True)
        await asyncio.sleep(interval_seconds)
