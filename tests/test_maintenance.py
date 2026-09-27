import os
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.maintenance import daily_maintenance, drop_old_daily_backups, drop_old_migration_copies, wipe_youtube_data
from tests.builders import insert_audit
from tests.fakes import FAKE_NOW


async def channel_rows(engine) -> list[tuple]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT channel_id, handle, status FROM audits ORDER BY id"))
        return [tuple(row) for row in rows]


async def test_wipe_clears_channel_data_older_than_twenty_days(db):
    await insert_audit(db, FAKE_NOW - timedelta(days=21), channel_id="UCold", handle="@old")
    await insert_audit(db, FAKE_NOW - timedelta(days=19), channel_id="UCnew", handle="@new")
    assert await wipe_youtube_data(db, FAKE_NOW) == 1
    assert await channel_rows(db) == [(None, None, "done"), ("UCnew", "@new", "done")]


async def test_daily_copy_is_taken_after_the_wipe(db, tmp_path):
    """Копия снимается после уборки: в ней нет данных YouTube старше 20 дней (ТЗ, Ю4)."""
    await insert_audit(db, FAKE_NOW - timedelta(days=25), channel_id="UCold", handle="@old")
    backups = tmp_path / "backups"
    await daily_maintenance(db, backups, FAKE_NOW)
    copy = create_async_engine(f"sqlite+aiosqlite:///{backups / 'bot-2026-09-25.db'}")
    try:
        assert await channel_rows(copy) == [(None, None, "done")]
    finally:
        await copy.dispose()


def test_daily_backups_older_than_a_week_by_name_are_removed_after_downtime(tmp_path):
    """Простой бота не должен продлить жизнь суточным копиям дольше их даты в имени (ТЗ, Р19, Ю4)."""
    fresh_day, old_day, today = (FAKE_NOW.date() - timedelta(days=3), FAKE_NOW.date() - timedelta(days=10),
                                 FAKE_NOW.date())
    fresh, old, current = (tmp_path / f"bot-{day.isoformat()}.db" for day in (fresh_day, old_day, today))
    garbage = tmp_path / "bot-not-a-date.db"
    for path in (fresh, old, current, garbage):
        path.write_bytes(b"copy")
    assert drop_old_daily_backups(tmp_path, FAKE_NOW) == [old]
    assert fresh.exists() and current.exists() and garbage.exists() and not old.exists()


def test_migration_copies_older_than_a_week_are_removed(tmp_path):
    """У чекера копии перед миграцией живут вечно; здесь — 7 дней, как суточные (ТЗ, раздел 12)."""
    old, fresh = tmp_path / "pre-v2-old.db", tmp_path / "pre-v2-fresh.db"
    for path, moment in ((old, FAKE_NOW - timedelta(days=8)), (fresh, FAKE_NOW)):
        path.write_bytes(b"copy")
        os.utime(path, (moment.timestamp(), moment.timestamp()))
    assert drop_old_migration_copies(tmp_path, FAKE_NOW) == [old]
    assert fresh.exists() and not old.exists()
