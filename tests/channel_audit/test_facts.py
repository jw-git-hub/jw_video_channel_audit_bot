from bot.channel_audit.collect import ChannelInfo
from bot.channel_audit.facts import build_facts
from bot.channel_audit.links import LinkHits
from tests.builders import CHANNEL, UPLOADS, video
from tests.fakes import FAKE_NOW

CHANNEL_INFO = ChannelInfo(CHANNEL, "Байк-прокат Пример", "@bike-example", "Сайт https://bike-example.com", UPLOADS)


def test_channel_without_public_videos_gets_only_links_from_its_description():
    facts = build_facts(CHANNEL_INFO, [video(1, broadcast="upcoming")], FAKE_NOW)
    assert not facts.has_videos
    assert (facts.rhythm, facts.formats, facts.ending, facts.views) == (None, None, None, ())
    assert facts.links.channel == LinkHits(sites=("bike-example.com",))
    assert facts.links.videos_checked == 0


def test_facts_of_a_working_channel():
    videos = [video(week * 7 + 1, "long", links=LinkHits(telegram=week == 0)) for week in range(20)]
    facts = build_facts(CHANNEL_INFO, videos, FAKE_NOW)
    assert (facts.channel_id, facts.title, facts.handle, facts.collected_at) == (
        CHANNEL, "Байк-прокат Пример", "@bike-example", FAKE_NOW)
    assert (facts.rhythm.count, facts.formats.long) == (20, 20)
    assert (facts.links.videos_checked, facts.links.telegram_videos) == (10, 1)
    assert facts.ending.active
