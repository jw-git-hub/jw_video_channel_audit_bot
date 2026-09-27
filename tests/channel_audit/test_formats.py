from bot.channel_audit.formats import Formats, formats
from bot.channel_audit.videos import Kind, usable
from tests.builders import days_ago, video


def test_formats_count_kinds_inside_the_coverage():
    videos = usable([video(1, "short"), video(2, "short"), video(3, "long"), video(4, "live"), video(300, "short")])
    result = formats(videos, days_ago(182))
    assert result == Formats(short=2, long=1, live=1)
    assert result.counts() == {Kind.SHORT: 2, Kind.LONG: 1, Kind.LIVE: 1}


def test_no_videos_in_coverage_means_no_block():
    assert formats(usable([video(300)]), days_ago(182)) is None
