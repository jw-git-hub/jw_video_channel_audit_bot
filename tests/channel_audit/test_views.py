from statistics import median

from bot.channel_audit.videos import Kind, usable
from bot.channel_audit.views import BestVideo, views_by_group
from tests.builders import video
from tests.fakes import FAKE_NOW


def group(videos, kind):
    return next(item for item in views_by_group(usable(videos), FAKE_NOW) if item.kind == kind)


def test_short_group_typical_and_latest_ten_skip_fresh_videos():
    videos = [video(5, "short", views=10_000)]  # моложе двух недель — ещё набирает просмотры
    videos += [video(20 + day, "short", views=1000 + day) for day in range(20)]
    short = group(videos, Kind.SHORT)
    assert short.typical == median(1000 + day for day in range(20))
    assert short.recent == median(1000 + day for day in range(10))


def test_long_videos_younger_than_sixty_days_are_not_counted():
    """Длинным просмотры месяцами приносят поиск и рекомендации (ТЗ, 6.2)."""
    videos = [video(30, "long", views=5)] + [video(61 + day, "long", views=100) for day in range(8)]
    assert group(videos, Kind.LONG).typical == 100


def test_group_needs_eight_videos_for_typical_and_fifteen_for_latest_ten():
    assert views_by_group(usable([video(70 + day) for day in range(7)]), FAKE_NOW) == ()
    eight = group([video(70 + day) for day in range(8)], Kind.LONG)
    assert (eight.typical, eight.recent) == (100, None)
    assert group([video(70 + day) for day in range(15)], Kind.LONG).recent == 100


def test_best_video_is_the_most_viewed_in_six_months_with_ratio_rounded_half_up():
    videos = [video(70 + day, "long", views=500) for day in range(10)]
    videos.append(video(80.5, "long", views=8437, title="Как выбрать байк", video_id="best"))
    videos.append(video(250, "long", views=99_999, video_id="old"))  # старше полугода — не «лучшее»
    assert group(videos, Kind.LONG).best == BestVideo("best", "Как выбрать байк", 8437, 17)


def test_no_ratio_below_two_or_when_typical_is_zero():
    near = [video(70 + day, "long", views=100) for day in range(8)] + [video(65, "long", views=149, video_id="b")]
    assert group(near, Kind.LONG).best.ratio is None
    zeros = [video(70 + day, "long", views=0) for day in range(8)] + [video(65, "long", views=50, video_id="z")]
    assert group(zeros, Kind.LONG).best.ratio is None


def test_videos_without_view_count_are_left_out():
    videos = [video(70 + day) for day in range(7)] + [video(90, views=None)]
    assert views_by_group(usable(videos), FAKE_NOW) == ()


def test_groups_come_short_long_live():
    videos = [video(70 + day, kind) for kind in ("live", "long", "short") for day in range(8)]
    assert [item.kind for item in views_by_group(usable(videos), FAKE_NOW)] == [Kind.SHORT, Kind.LONG, Kind.LIVE]
