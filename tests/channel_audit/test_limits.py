from datetime import timedelta

import pytest

from bot.channel_audit.audits import DONE, RUNNING, AuditsRepo, Closing, NewAudit
from bot.channel_audit.limits import LIMIT_GLOBAL, LIMIT_USER, Limits, hours_until
from bot.core.users import Users
from tests.builders import CHANNEL
from tests.fakes import ADMIN_ID, FAKE_NOW, FakeClock

USER = 77
OTHER = 78
STRANGER = 500


@pytest.fixture
async def repo(db):
    clock = FakeClock()
    for user_id in (USER, OTHER, ADMIN_ID):
        await Users(db, clock).touch(user_id, "ru")
    return AuditsRepo(db, clock)


async def audit(repo: AuditsRepo, user_id: int = USER, api_units: int = 3) -> None:
    audit_id = await repo.create(NewAudit(user_id, "direct", "handle", RUNNING))
    await repo.finish(audit_id, Closing(DONE, channel_id=CHANNEL, charged=True, api_units=api_units))


async def test_user_limit_says_when_the_next_attempt_opens(repo):
    await audit(repo)
    await audit(repo)
    clock = FakeClock()
    clock.advance(3600)
    decision = await Limits(repo, clock, user_daily=2, global_daily=100, admin_id=ADMIN_ID).decide(USER, True)
    assert (decision.allowed, decision.code) == (False, LIMIT_USER)
    assert hours_until(decision.reopens_at, clock.now()) == 23


async def test_global_ceiling_counts_only_audits_that_went_to_google(repo):
    limits = Limits(repo, FakeClock(), user_daily=10, global_daily=2, admin_id=ADMIN_ID)
    await audit(repo)
    await audit(repo, user_id=OTHER, api_units=0)  # отчёт из кэша: квоту не тратил
    assert (await limits.decide(STRANGER, uses_google=True)).allowed
    await audit(repo, user_id=OTHER)
    blocked = await limits.decide(STRANGER, uses_google=True)
    assert (blocked.code, blocked.reopens_at) == (LIMIT_GLOBAL, FAKE_NOW + timedelta(hours=24))


async def test_channel_from_the_cache_passes_the_global_ceiling(repo):
    limits = Limits(repo, FakeClock(), user_daily=10, global_daily=1, admin_id=ADMIN_ID)
    await audit(repo, user_id=OTHER)
    assert (await limits.decide(USER, uses_google=False)).allowed


async def test_owner_has_no_limits(repo):
    await audit(repo, user_id=ADMIN_ID)
    limits = Limits(repo, FakeClock(), user_daily=1, global_daily=1, admin_id=ADMIN_ID)
    assert (await limits.decide(ADMIN_ID, uses_google=True)).allowed


class BrokenRepo:
    async def count_charged_since(self, since, user_id):
        raise RuntimeError("база недоступна")


async def test_limits_fall_back_to_memory_when_database_is_down():
    limits = Limits(BrokenRepo(), FakeClock(), user_daily=1, global_daily=2, admin_id=ADMIN_ID)
    assert (await limits.decide(USER, uses_google=True)).allowed
    limits.remember(USER, charged=True, used_google=True)
    assert (await limits.decide(USER, uses_google=True)).code == LIMIT_USER
    limits.remember(OTHER, charged=True, used_google=True)
    assert (await limits.decide(STRANGER, uses_google=True)).code == LIMIT_GLOBAL


async def test_memory_forgets_attempts_older_than_the_window(repo):
    """remember пишется и при исправной базе — без своей обрезки память росла бы всю жизнь процесса."""
    clock = FakeClock()
    limits = Limits(repo, clock, user_daily=10, global_daily=10, admin_id=ADMIN_ID)
    limits.remember(USER, charged=True, used_google=True)
    clock.advance(timedelta(hours=25).total_seconds())
    limits.remember(USER, charged=True, used_google=False)
    assert len(limits._memory) == 1


def test_hours_until_rounds_up_and_is_at_least_one():
    assert hours_until(FAKE_NOW + timedelta(minutes=61), FAKE_NOW) == 2
    assert hours_until(FAKE_NOW - timedelta(minutes=5), FAKE_NOW) == 1
