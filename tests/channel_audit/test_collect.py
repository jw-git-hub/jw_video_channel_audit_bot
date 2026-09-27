import pytest

from bot.channel_audit.collect import CHANNEL_FIELDS, MAX_PAGES, PAGE_FIELDS, ChannelInfo, ChannelNotFound, Collector
from bot.channel_audit.input import CHANNEL_ID, HANDLE, LEGACY, USERNAME, VIDEO, Target
from bot.channel_audit.links import LinkHits
from bot.channel_audit.videos import Kind
from bot.channel_audit.youtube import Meter, NotFound, ServiceDown
from tests.builders import (CHANNEL, UPLOADS, ScriptedClient, channel_item, days_ago, page, page_entry,
                            video_item)
from tests.fakes import FakeClock

DEADLINE = 30.0


def collector(client: ScriptedClient) -> Collector:
    return Collector(client, FakeClock())


def found() -> dict:
    return {"items": [channel_item()]}


async def test_handle_is_looked_up_with_at_sign_and_needed_fields_only():
    client = ScriptedClient()
    client.channels["@bike_example"] = found()
    meter = Meter()
    info = await collector(client).find_channel(Target(HANDLE, "bike_example"), DEADLINE, meter)
    assert info == ChannelInfo(CHANNEL, "Байк-прокат Пример", "@bike-example", "", UPLOADS)
    assert client.calls == [("channels", {"part": "snippet,contentDetails", "forHandle": "@bike_example",
                                          "fields": CHANNEL_FIELDS})]
    assert meter.units == 1


@pytest.mark.parametrize(("target", "key"), [(Target(CHANNEL_ID, CHANNEL), CHANNEL),
                                             (Target(USERNAME, "BikeUser"), "BikeUser"),
                                             (Target(LEGACY, "BikeName"), "@BikeName")])
async def test_id_username_and_old_address_lookups(target, key):
    client = ScriptedClient()
    client.channels[key] = found()
    assert (await collector(client).find_channel(target, DEADLINE, Meter())).channel_id == CHANNEL


async def test_bare_old_address_tries_the_old_username_second():
    client = ScriptedClient()
    client.channels["BikeName"] = found()
    meter = Meter()
    info = await collector(client).find_channel(Target(LEGACY, "BikeName", bare=True), DEADLINE, meter)
    assert info.channel_id == CHANNEL
    assert [params.get("forHandle") or params.get("forUsername") for _, params in client.calls] == ["@BikeName",
                                                                                                     "BikeName"]
    assert meter.units == 2


@pytest.mark.parametrize("target", [Target(LEGACY, "BikeName"), Target(LEGACY, "BikeName", bare=True)])
async def test_old_address_not_found(target):
    with pytest.raises(ChannelNotFound) as missing:
        await collector(ScriptedClient()).find_channel(target, DEADLINE, Meter())
    assert missing.value.args[0] == LEGACY


async def test_not_found_answer_from_google_is_a_missing_channel():
    client = ScriptedClient()
    client.channels[CHANNEL] = NotFound("channelNotFound")
    with pytest.raises(ChannelNotFound) as missing:
        await collector(client).find_channel(Target(CHANNEL_ID, CHANNEL), DEADLINE, Meter())
    assert missing.value.args[0] == CHANNEL_ID


async def test_video_link_gives_the_channel_of_the_video():
    client = ScriptedClient()
    client.video_channels["Ab3dE5gH1jK"] = {"items": [{"snippet": {"channelId": CHANNEL}}]}
    client.channels[CHANNEL] = found()
    info = await collector(client).find_channel(Target(VIDEO, "Ab3dE5gH1jK"), DEADLINE, Meter())
    assert info.channel_id == CHANNEL
    assert client.methods() == ["videos", "channels"]


async def test_deleted_or_private_video_is_video_not_found():
    with pytest.raises(ChannelNotFound) as missing:
        await collector(ScriptedClient()).find_channel(Target(VIDEO, "Ab3dE5gH1jK"), DEADLINE, Meter())
    assert missing.value.args[0] == VIDEO


def full_page(start: int, days_from: float, next_token: str | None) -> dict:
    return page([page_entry(f"v{start + index}", days_ago(days_from + index * 0.1)) for index in range(50)],
                next_token)


async def test_paging_stops_at_two_hundred_videos():
    client = ScriptedClient()
    tokens = [None, "p2", "p3", "p4", "p5"]
    for number, token in enumerate(tokens):
        client.pages[token] = full_page(number * 50, number * 5, tokens[number + 1] if number < 4 else "p6")
    videos = await collector(client).videos(UPLOADS, DEADLINE, Meter())
    assert client.methods().count("playlistItems") == 4
    assert client.methods().count("videos") == 4
    assert all(len(params["id"].split(",")) == 50 for method, params in client.calls if method == "videos")
    assert videos == []  # у подделки нет подробностей видео — важно, сколько запросов ушло


async def test_paging_follows_next_page_token_until_it_ends():
    client = ScriptedClient()
    client.pages[None] = full_page(0, 1, "p2")
    client.pages["p2"] = page([page_entry("last", days_ago(40))])
    await collector(client).videos(UPLOADS, DEADLINE, Meter())
    assert client.methods().count("playlistItems") == 2
    assert "nextPageToken" in PAGE_FIELDS


async def test_one_more_page_after_crossing_twelve_months_then_stop():
    client = ScriptedClient()
    client.pages[None] = full_page(0, 300, "p2")
    client.pages["p2"] = page([page_entry("old", days_ago(400))], "p3")
    client.pages["p3"] = page([page_entry("older", days_ago(420))], "p4")
    await collector(client).videos(UPLOADS, DEADLINE, Meter())
    assert [params.get("pageToken") for method, params in client.calls if method == "playlistItems"] == [None, "p2",
                                                                                                          "p3"]


async def test_undated_pages_stop_after_max_pages():
    """Плейлист сплошь без дат раньше листался до самого срока аудита (F7) — теперь ограничен MAX_PAGES."""
    client = ScriptedClient()
    undated_page = page([{"contentDetails": {"videoId": "novideo"}}], "next")
    client.pages[None] = undated_page
    client.pages["next"] = undated_page
    videos = await collector(client).videos(UPLOADS, DEADLINE, Meter())
    assert client.methods().count("playlistItems") == MAX_PAGES
    assert videos == []


async def test_private_items_without_date_are_skipped_and_details_come_in_batches():
    client = ScriptedClient()
    entries = [page_entry(f"v{index}", days_ago(index)) for index in range(1, 121)] + [page_entry("private", None)]
    client.pages[None] = page(entries)
    for index in range(1, 121):
        client.videos[f"v{index}"] = video_item(f"v{index}", days_ago(index))
    videos = await collector(client).videos(UPLOADS, DEADLINE, Meter())
    sizes = [len(params["id"].split(",")) for method, params in client.calls if method == "videos"]
    assert sizes == [50, 50, 20]
    assert len(videos) == 120


async def test_missing_uploads_playlist_gives_no_videos():
    client = ScriptedClient()
    client.pages[None] = NotFound("playlistNotFound")
    assert await collector(client).videos(UPLOADS, DEADLINE, Meter()) == []
    assert await collector(client).videos(None, DEADLINE, Meter()) == []


async def test_video_details_are_parsed_and_descriptions_become_link_hits():
    client = ScriptedClient()
    published = days_ago(3)
    client.pages[None] = page([page_entry("live1", published), page_entry("noviews", published)])
    client.videos["live1"] = video_item("live1", published, duration="P0D", live=True,
                                        description="Чат: https://t.me/bike_example")
    client.videos["noviews"] = video_item("noviews", published, views=None, broadcast="upcoming")
    live, upcoming = await collector(client).videos(UPLOADS, DEADLINE, Meter())
    assert (live.kind, live.duration_seconds, live.views, live.links) == (Kind.LIVE, 0, 100, LinkHits(telegram=True))
    assert (upcoming.views, upcoming.broadcast) == (None, "upcoming")


async def test_not_found_on_a_video_batch_is_service_down_not_a_bug():
    """4xx на videos.list по ID из плейлиста — не о присланном канале (F9): не списывается, не «упал» (Ю4)."""
    class NotFoundVideos(ScriptedClient):
        async def call(self, method, params, deadline, meter):
            if method == "videos":
                self.calls.append((method, dict(params)))
                meter.units += 1
                raise NotFound("videoNotFound")
            return await super().call(method, params, deadline, meter)

    client = NotFoundVideos()
    client.pages[None] = page([page_entry("v1", days_ago(1))])
    with pytest.raises(ServiceDown, match="shape"):
        await collector(client).videos(UPLOADS, DEADLINE, Meter())


async def test_items_that_are_not_a_list_mean_a_changed_answer():
    client = ScriptedClient()
    client.channels["@bike_example"] = {"items": "не список"}
    with pytest.raises(ServiceDown, match="shape"):
        await collector(client).find_channel(Target(HANDLE, "bike_example"), DEADLINE, Meter())
