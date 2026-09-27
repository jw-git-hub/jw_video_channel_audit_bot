import pytest

from bot.channel_audit.audit import LEGACY_NOT_FOUND, NOT_FOUND, QUOTA, SERVICE_DOWN, VIDEO_NOT_FOUND, Auditor
from bot.channel_audit.cache import DayCache
from bot.channel_audit.collect import Collector
from bot.channel_audit.input import CHANNEL_ID, HANDLE, LEGACY, VIDEO, Target
from bot.channel_audit.youtube import Meter, QuotaExhausted, ServiceDown
from tests.builders import CHANNEL, ScriptedClient, channel_item, days_ago, page, page_entry, video_item
from tests.fakes import FakeClock

DEADLINE = 30.0


def auditor(client: ScriptedClient) -> Auditor:
    clock = FakeClock()
    return Auditor(Collector(client, clock), DayCache(clock), DayCache(clock), clock)


def working_client() -> ScriptedClient:
    client = ScriptedClient()
    client.channels["@bike_example"] = {"items": [channel_item()]}
    client.channels[CHANNEL] = {"items": [channel_item()]}
    client.pages[None] = page([page_entry("v1", days_ago(3))])
    client.videos["v1"] = video_item("v1", days_ago(3))
    return client


async def test_first_audit_collects_and_the_same_handle_in_other_case_comes_from_cache():
    client = working_client()
    audits = auditor(client)
    first = await audits.run(Target(HANDLE, "bike_example"), DEADLINE, Meter())
    assert (first.from_cache, first.units, first.charged, first.facts.channel_id) == (False, 3, True, CHANNEL)
    second = await audits.run(Target(HANDLE, "Bike_Example"), DEADLINE, Meter())
    assert (second.from_cache, second.units, second.charged) == (True, 0, True)
    assert len(client.calls) == 3
    assert audits.cached(Target(HANDLE, "BIKE_EXAMPLE")) is second.facts


async def test_other_input_for_the_same_channel_reuses_its_facts_after_one_lookup():
    client = working_client()
    audits = auditor(client)
    await audits.run(Target(HANDLE, "bike_example"), DEADLINE, Meter())
    again = await audits.run(Target(CHANNEL_ID, CHANNEL), DEADLINE, Meter())
    assert (again.from_cache, again.units) == (True, 1)


@pytest.mark.parametrize(("target", "code"), [(Target(HANDLE, "nobody"), NOT_FOUND),
                                              (Target(LEGACY, "Nobody"), LEGACY_NOT_FOUND),
                                              (Target(VIDEO, "Ab3dE5gH1jK"), VIDEO_NOT_FOUND)])
async def test_missing_channel_codes_are_charged(target, code):
    outcome = await auditor(ScriptedClient()).run(target, DEADLINE, Meter())
    assert (outcome.error_code, outcome.charged, outcome.facts) == (code, True, None)
    assert outcome.units >= 1


async def test_quota_and_service_down_are_not_charged():
    client = ScriptedClient()
    client.channels["@bike_example"] = QuotaExhausted("ceiling")
    blocked = await auditor(client).run(Target(HANDLE, "bike_example"), DEADLINE, Meter())
    assert (blocked.error_code, blocked.reason, blocked.charged) == (QUOTA, "ceiling", False)
    client.channels["@bike_example"] = ServiceDown("key")
    down = await auditor(client).run(Target(HANDLE, "bike_example"), DEADLINE, Meter())
    assert (down.error_code, down.reason, down.charged) == (SERVICE_DOWN, "key", False)
