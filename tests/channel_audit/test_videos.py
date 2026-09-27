import pytest

from bot.channel_audit.links import LinkHits
from bot.channel_audit.videos import Kind, Video, duration_seconds, usable
from tests.builders import days_ago


def make(days: float, duration: int = 600, live: bool = False, broadcast: str = "none") -> Video:
    return Video(f"v{days}", "Видео", days_ago(days), duration, 100, live, broadcast, LinkHits())


@pytest.mark.parametrize(("value", "seconds"), [("PT1M5S", 65), ("PT3M", 180), ("PT2H", 7200), ("P1DT3M", 86_580),
                                                ("P0D", 0), ("", 0), ("мусор", 0)])
def test_duration_seconds(value, seconds):
    assert duration_seconds(value) == seconds


def test_kind_by_duration_and_live_details():
    assert make(1, duration=180).kind == Kind.SHORT
    assert make(1, duration=181).kind == Kind.LONG
    assert make(1, duration=30, live=True).kind == Kind.LIVE


def test_usable_drops_upcoming_and_live_now_and_sorts_newest_first():
    videos = [make(5), make(1), make(0.5, broadcast="upcoming"), make(0.1, broadcast="live"), make(3)]
    assert [video.video_id for video in usable(videos)] == ["v1", "v3", "v5"]
