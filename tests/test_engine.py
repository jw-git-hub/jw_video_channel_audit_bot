"""Движок базы под политику данных (F1, F2): параметры не в тексте ошибки, стёртое не читается из файла."""
from datetime import timedelta

from sqlalchemy import text

from bot.channel_audit.audits import AuditsRepo
from bot.channel_audit.thresholds import API_DATA_DAYS
from bot.core.db import migrate
from bot.engine import open_engine
from bot.maintenance import wipe_youtube_data
from bot.schema import MIGRATIONS
from tests.builders import insert_audit
from tests.fakes import FAKE_NOW, FakeClock

MARKER_VALUE = "UCsecretmarkeraaaaaaaaaa"  # похоже на channel_id — не должно попасть в текст ошибки
WIPED_MARKER = "@marker-wiped-handle-example"
FORGOTTEN_MARKER = "@marker-forgotten-handle-example"
WIPED_USER = 201
FORGOTTEN_USER = 202


async def test_a_failing_statement_does_not_print_its_parameters(tmp_path):
    engine = open_engine(tmp_path / "data")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE probe (value TEXT UNIQUE)"))
            await connection.execute(text("INSERT INTO probe (value) VALUES (:value)"), {"value": MARKER_VALUE})
        text_of_error = None
        try:
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO probe (value) VALUES (:value)"), {"value": MARKER_VALUE})
        except Exception as error:  # noqa: BLE001 — сам факт ошибки тут не важен, важен только её текст
            text_of_error = str(error)
        assert text_of_error is not None, "нарушение UNIQUE не привело к ошибке"
    finally:
        await engine.dispose()
    assert MARKER_VALUE not in text_of_error
    assert "hide_parameters=True" in text_of_error


async def test_wiped_and_forgotten_data_is_not_readable_in_the_file(tmp_path):
    data_dir = tmp_path / "data"
    engine = open_engine(data_dir)
    await migrate(engine, MIGRATIONS, tmp_path / "backups", "t")
    await insert_audit(engine, FAKE_NOW - timedelta(days=API_DATA_DAYS + 1), channel_id="UCwiped012345678901234",
                       handle=WIPED_MARKER, user_id=WIPED_USER)
    await insert_audit(engine, FAKE_NOW, channel_id="UCforgot01234567890123", handle=FORGOTTEN_MARKER,
                       user_id=FORGOTTEN_USER)
    await wipe_youtube_data(engine, FAKE_NOW)
    await AuditsRepo(engine, FakeClock()).forget_user(FORGOTTEN_USER)
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    await engine.dispose()
    raw = (data_dir / "bot.db").read_bytes()
    assert WIPED_MARKER.encode() not in raw
    assert FORGOTTEN_MARKER.encode() not in raw
