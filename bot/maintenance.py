"""Суточное обслуживание базы (ТЗ, раздел 12, Ю4): сначала уборка данных YouTube, потом копия.

Порядок важен: копия снимается уже после уборки, поэтому ни в базе, ни в копиях данные YouTube не старше
1 (кэш) + 20 + 1 + 7 = 29 дней. Копии перед миграцией (core/db.py) у чекера живут вечно — здесь они удаляются
через 7 дней, как суточные.
"""
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.channel_audit.thresholds import API_DATA_DAYS
from bot.core.clock import to_iso
from bot.core.db import DAILY_BACKUP_PREFIX, backup_daily, daily_backup_path
from bot.engine import flush_deleted

PRE_MIGRATION_GLOB = "pre-v*.db"
SECONDS_IN_DAY = 86_400
BACKUP_KEEP_DAYS = 7  # суточные и предмиграционные копии живут не дольше — даже после простоя (ТЗ, Р19, Ю4)
WIPE = """
UPDATE audits SET channel_id = NULL, handle = NULL
WHERE created_at < :before AND (channel_id IS NOT NULL OR handle IS NOT NULL)"""


async def wipe_youtube_data(engine: AsyncEngine, now: datetime) -> int:
    before = to_iso(now - timedelta(days=API_DATA_DAYS))
    async with engine.begin() as connection:
        rowcount = (await connection.execute(text(WIPE), {"before": before})).rowcount
    await flush_deleted(engine)
    return rowcount


def drop_old_migration_copies(backup_dir: Path, now: datetime) -> list[Path]:
    limit = now.timestamp() - BACKUP_KEEP_DAYS * SECONDS_IN_DAY
    old = sorted(path for path in backup_dir.glob(PRE_MIGRATION_GLOB) if path.stat().st_mtime < limit)
    for path in old:
        path.unlink()
    return old


def drop_old_daily_backups(backup_dir: Path, now: datetime) -> list[Path]:
    """По дате в имени, не по времени работы бота: простой дольше недели не продлевает копиям жизнь (ТЗ, Р19)."""
    cutoff = now.date() - timedelta(days=BACKUP_KEEP_DAYS)
    days = {path: _backup_day(path) for path in backup_dir.glob(f"{DAILY_BACKUP_PREFIX}*.db")}
    old = sorted(path for path, day in days.items() if day is not None and day < cutoff)
    for path in old:
        path.unlink()
    return old


def _backup_day(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem.removeprefix(DAILY_BACKUP_PREFIX))
    except ValueError:
        return None


async def daily_maintenance(engine: AsyncEngine, backup_dir: Path, now: datetime) -> None:
    """Уборка → копия за день (одна: перезапуск не затирает утреннюю) → старые копии по дате, затем перед миграцией."""
    await wipe_youtube_data(engine, now)
    if not daily_backup_path(backup_dir, now.date()).exists():
        await backup_daily(engine, backup_dir, now.date())
    drop_old_daily_backups(backup_dir, now)
    drop_old_migration_copies(backup_dir, now)
