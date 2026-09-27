from bot.channel_audit.ending import Ending, TelegramPlace, ending, telegram_place
from bot.channel_audit.links import LinkHits, LinkSummary
from bot.channel_audit.videos import usable
from tests.builders import video
from tests.fakes import FAKE_NOW


def summary(channel: LinkHits | None = None, telegram_videos: int = 0) -> LinkSummary:
    return LinkSummary(channel, 10, telegram_videos, 0, 0, None)


def test_two_videos_in_sixty_days_mean_videos_come_out():
    videos = usable([video(5), video(59), video(100)])
    assert ending(videos, summary(), FAKE_NOW) == Ending(True, 1, TelegramPlace.NOWHERE)


def test_pace_is_videos_in_sixty_days_halved_and_rounded_half_up():
    assert ending(usable([video(day) for day in range(1, 60, 6)]), summary(), FAKE_NOW).pace == 5
    assert ending(usable([video(1), video(20), video(40)]), summary(), FAKE_NOW).pace == 2  # 1,5 → 2


def test_one_video_in_sixty_days_is_not_active():
    assert not ending(usable([video(10), video(90)]), summary(), FAKE_NOW).active


def test_telegram_place():
    assert telegram_place(summary(telegram_videos=2)) == TelegramPlace.UNDER_VIDEOS
    assert telegram_place(summary(channel=LinkHits(telegram=True))) == TelegramPlace.CHANNEL_ONLY
    assert telegram_place(summary(channel=LinkHits(sites=("a-example.com",)))) == TelegramPlace.NOWHERE
    assert telegram_place(summary()) == TelegramPlace.NOWHERE
