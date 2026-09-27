from datetime import timedelta

from bot.channel_audit.cache import DayCache, target_key
from bot.channel_audit.input import CHANNEL_ID, HANDLE, LEGACY, VIDEO, Target
from tests.fakes import FakeClock


def test_handle_key_ignores_case_but_ids_do_not():
    assert target_key(Target(HANDLE, "Bike_Example")) == target_key(Target(HANDLE, "bike_example"))
    assert target_key(Target(CHANNEL_ID, "UCabc")) != target_key(Target(CHANNEL_ID, "UCABC"))
    assert target_key(Target(VIDEO, "Ab3dE5gH1jK")) != target_key(Target(VIDEO, "ab3de5gh1jk"))
    assert target_key(Target(LEGACY, "Name")) != target_key(Target(LEGACY, "Name", bare=True))


def test_values_live_one_day():
    clock = FakeClock()
    cache = DayCache[str](clock)
    cache.put("k", "v")
    clock.advance(timedelta(hours=23).total_seconds())
    assert cache.get("k") == "v"
    clock.advance(timedelta(hours=2).total_seconds())
    assert cache.get("k") is None


def test_least_recently_used_value_goes_first_when_full():
    cache = DayCache[str](FakeClock(), max_items=2)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.get("a")
    cache.put("c", "3")
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == ("1", None, "3")
