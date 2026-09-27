from bot.channel_audit.kv import Kv
from bot.channel_audit.quota import CEILING, QUOTA, QuotaGate, hours_until_reset, pacific_day
from tests.fakes import FAKE_NOW, FakeClock

HOURS_TO_PACIFIC_MIDNIGHT = 19  # 25.09.2026 12:00 UTC — это 05:00 по тихоокеанскому летнему времени
SECONDS_IN_HOUR = 3600


def test_pacific_day_and_hours_until_reset():
    assert pacific_day(FAKE_NOW).isoformat() == "2026-09-25"
    assert hours_until_reset(FAKE_NOW) == HOURS_TO_PACIFIC_MIDNIGHT


async def test_ceiling_blocks_until_pacific_midnight(db):
    clock = FakeClock()
    gate = QuotaGate(Kv(db), clock, ceiling=5)
    await gate.spend(4)
    assert gate.block_reason() is None
    await gate.spend(1)
    assert gate.block_reason() == CEILING
    clock.advance(HOURS_TO_PACIFIC_MIDNIGHT * SECONDS_IN_HOUR)
    assert gate.block_reason() is None
    assert gate.units_today() == 0


async def test_quota_exceeded_blocks_the_rest_of_the_day(db):
    gate = QuotaGate(Kv(db), FakeClock(), ceiling=8000)
    await gate.exhaust()
    assert gate.block_reason() == QUOTA
    assert gate.hours_left() == HOURS_TO_PACIFIC_MIDNIGHT


async def test_restart_keeps_todays_count_and_forgets_yesterdays(db):
    clock = FakeClock()
    gate = QuotaGate(Kv(db), clock, ceiling=10)
    await gate.spend(7)
    await gate.exhaust()
    restarted = QuotaGate(Kv(db), clock, ceiling=10)
    await restarted.load()
    assert (restarted.units_today(), restarted.block_reason()) == (7, QUOTA)
    clock.advance(24 * SECONDS_IN_HOUR)
    next_day = QuotaGate(Kv(db), clock, ceiling=10)
    await next_day.load()
    assert (next_day.units_today(), next_day.block_reason()) == (0, None)


class BrokenKv:
    async def get(self, key):
        raise RuntimeError("база недоступна")

    async def set(self, key, value):
        raise RuntimeError("база недоступна")


async def test_broken_database_keeps_counting_in_memory():
    gate = QuotaGate(BrokenKv(), FakeClock(), ceiling=2)
    await gate.load()
    await gate.spend(2)
    assert gate.block_reason() == CEILING
