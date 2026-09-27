from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bot.channel_audit.audits import DONE, FAILED, INTERRUPTED, RUNNING, AuditsRepo, Closing, NewAudit
from bot.core.users import Users
from tests.builders import CHANNEL
from tests.fakes import FAKE_NOW, FakeClock

USER = 77
OTHER = 78
UNKNOWN_USER_ID = 999
DAY_AGO = FAKE_NOW - timedelta(hours=24)
REPORT = Closing(DONE, channel_id=CHANNEL, handle="@Bike-Example", charged=True, api_units=3, offered=True)


@pytest.fixture
async def repo(db):
    clock = FakeClock()
    for user_id, label in ((USER, "channel"), (OTHER, "fb")):
        await Users(db, clock).touch(user_id, "ru", label)
    return AuditsRepo(db, clock)


async def add(repo: AuditsRepo, user_id: int = USER, source: str = "channel", closing: Closing = REPORT) -> int:
    audit_id = await repo.create(NewAudit(user_id, source, "handle", RUNNING, chat_id=user_id, message_id=5))
    await repo.finish(audit_id, closing)
    return audit_id


async def column(db, sql: str) -> list:
    async with db.connect() as connection:
        return (await connection.execute(text(sql))).scalars().all()


async def test_charged_audits_are_counted_per_user(repo):
    await add(repo)
    await add(repo, closing=Closing(FAILED, "service_down"))
    await add(repo, user_id=OTHER, source="fb")
    assert await repo.count_charged_since(DAY_AGO, USER) == 1
    assert await repo.oldest_charged_since(DAY_AGO, USER) == FAKE_NOW


async def test_only_audits_that_went_to_google_count_for_the_ceiling(repo):
    await add(repo)
    await add(repo, closing=Closing(DONE, channel_id=CHANNEL, from_cache=True, charged=True))
    assert await repo.count_google_since(DAY_AGO) == 1
    assert await repo.oldest_google_since(DAY_AGO) == FAKE_NOW


async def test_handle_is_stored_in_lower_case_and_found_by_handle_or_id(repo, db):
    await add(repo)
    assert await column(db, "SELECT handle FROM audits") == ["@bike-example"]
    by_handle = await repo.recent_for_channel(None, "@Bike-EXAMPLE", DAY_AGO)
    assert by_handle == await repo.recent_for_channel(CHANNEL, None, DAY_AGO)
    assert (by_handle[0].source, by_handle[0].status, by_handle[0].from_cache, by_handle[0].offered) == (
        "channel", DONE, False, True)


async def test_recent_for_channel_is_the_latest_five_inside_the_window(repo):
    for _ in range(6):
        await add(repo)
    assert len(await repo.recent_for_channel(CHANNEL, None, DAY_AGO)) == 5
    assert await repo.recent_for_channel(CHANNEL, None, FAKE_NOW + timedelta(seconds=1)) == []


async def test_running_audits_are_interrupted_and_uncharged(repo, db):
    audit_id = await repo.create(NewAudit(USER, "channel", "video", RUNNING, chat_id=USER, message_id=9))
    unfinished = await repo.interrupt_unfinished()
    assert [(item.audit_id, item.chat_id, item.message_id, item.lang) for item in unfinished] == [
        (audit_id, USER, 9, "ru")]
    assert await column(db, "SELECT status || ':' || charged FROM audits") == [f"{INTERRUPTED}:0"]
    assert await repo.interrupt_unfinished() == []


async def test_stats_by_label(repo):
    await add(repo)
    await add(repo, closing=Closing(DONE, channel_id=CHANNEL, from_cache=True, charged=True))
    await repo.create(NewAudit(OTHER, "fb", None, FAILED, "not_a_link"))
    rows, refusals = await repo.stats(FAKE_NOW - timedelta(days=7))
    by_label = {row.source: row for row in rows}
    channel, fb = by_label["channel"], by_label["fb"]
    assert (channel.new_users, channel.reported_users, channel.audits, channel.from_cache, channel.offered,
            channel.refusals) == (1, 1, 2, 1, 1, 0)
    assert (fb.new_users, fb.reported_users, fb.audits, fb.refusals) == (1, 0, 1, 1)
    assert refusals == [("not_a_link", 1)]


async def test_forget_removes_the_person_and_their_audits(repo, db):
    await add(repo)
    await add(repo)
    await add(repo, user_id=OTHER, source="fb")
    assert await repo.forget_user(USER) == 2
    assert await column(db, "SELECT user_id FROM users") == [OTHER]
    assert await column(db, "SELECT user_id FROM audits") == [OTHER]


async def test_create_rejects_audit_for_unknown_user(repo):
    """Человек должен быть в users до записи аудита: Users.touch — обязанность вызывающего, как у чекера."""
    with pytest.raises(IntegrityError):
        await repo.create(NewAudit(UNKNOWN_USER_ID, "direct", None, FAILED, "not_text"))
