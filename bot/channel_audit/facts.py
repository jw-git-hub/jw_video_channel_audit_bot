"""Факты отчёта (ТЗ, 5.2, 6.1–6.6): итоги подсчётов без привязки к языку.

Из них собирается отчёт на любом языке, их же кладёт кэш на сутки. Списка видео и описаний здесь нет — только
итоги, название и ID лучших видео и итоги по ссылкам.
"""
from dataclasses import dataclass
from datetime import datetime

from bot.channel_audit.collect import ChannelInfo
from bot.channel_audit.ending import Ending, ending
from bot.channel_audit.formats import Formats, formats
from bot.channel_audit.links import LinkSummary, summarize
from bot.channel_audit.rhythm import Rhythm, rhythm
from bot.channel_audit.thresholds import LINKS_VIDEOS
from bot.channel_audit.videos import Video, usable
from bot.channel_audit.views import GroupViews, views_by_group


@dataclass(frozen=True)
class Facts:
    channel_id: str
    title: str
    handle: str | None
    collected_at: datetime
    links: LinkSummary
    rhythm: Rhythm | None = None  # None — на канале нет открытых видео: короткий отчёт (ТЗ, 6.6)
    views: tuple[GroupViews, ...] = ()
    formats: Formats | None = None
    ending: Ending | None = None

    @property
    def has_videos(self) -> bool:
        return self.rhythm is not None


def build_facts(channel: ChannelInfo, videos: list[Video], now: datetime) -> Facts:
    shown = usable(videos)
    links = summarize(channel.description, [video.links for video in shown[:LINKS_VIDEOS]])
    if not shown:
        return Facts(channel.channel_id, channel.title, channel.handle, now, links)
    channel_rhythm = rhythm(shown, now)
    return Facts(channel.channel_id, channel.title, channel.handle, now, links, channel_rhythm,
                 views_by_group(shown, now), formats(shown, channel_rhythm.since), ending(shown, links, now))
