"""Вывод (ТЗ, 6.5): видео выходят — темп сейчас и где ссылка на Telegram; не выходят — без предложения пакета."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from bot.channel_audit.links import LinkSummary
from bot.channel_audit.thresholds import ACTIVE_DAYS, ACTIVE_MIN_VIDEOS, ACTIVE_MONTHS
from bot.channel_audit.videos import Video
from bot.channel_audit.wording import round_half_up


class TelegramPlace(StrEnum):
    NOWHERE = "nowhere"
    CHANNEL_ONLY = "channel_only"
    UNDER_VIDEOS = "under_videos"


@dataclass(frozen=True)
class Ending:
    active: bool  # за 60 дней вышло хотя бы 2 видео — есть предложение пакета
    pace: int  # видео в месяц сейчас: за 60 дней ÷ 2, половина — вверх
    telegram: TelegramPlace


def ending(videos: list[Video], links: LinkSummary, now: datetime) -> Ending:
    since = now - timedelta(days=ACTIVE_DAYS)
    recent = sum(1 for video in videos if video.published >= since)
    return Ending(recent >= ACTIVE_MIN_VIDEOS, int(round_half_up(recent / ACTIVE_MONTHS)), telegram_place(links))


def telegram_place(links: LinkSummary) -> TelegramPlace:
    if links.telegram_videos:
        return TelegramPlace.UNDER_VIDEOS
    if links.channel is not None and links.channel.telegram:
        return TelegramPlace.CHANNEL_ONLY
    return TelegramPlace.NOWHERE
