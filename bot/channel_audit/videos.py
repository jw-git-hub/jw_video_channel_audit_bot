"""Видео и его вид (ТЗ, 6.0): эфир, короткое, длинное; какие видео считаются."""
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from bot.channel_audit.links import LinkHits
from bot.channel_audit.thresholds import SHORT_MAX_SECONDS

NOT_A_BROADCAST = "none"  # liveBroadcastContent: не предстоящий и не идущий сейчас эфир
DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")
SECONDS_IN = (86_400, 3600, 60, 1)  # день, час, минута, секунда — по группам DURATION


class Kind(StrEnum):
    SHORT = "short"
    LONG = "long"
    LIVE = "live"


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    published: datetime
    duration_seconds: int
    views: int | None  # None — нет statistics.viewCount: в «Отдачу» не идёт, в ритм и форматы — идёт (6.0)
    live_details: bool  # есть liveStreamingDetails — эфир
    broadcast: str  # liveBroadcastContent: none, upcoming, live
    links: LinkHits

    @property
    def kind(self) -> Kind:
        """Короткое — по длительности, а не «Shorts»: признака Shorts в API нет (ТЗ, Ю2)."""
        if self.live_details:
            return Kind.LIVE
        return Kind.SHORT if self.duration_seconds <= SHORT_MAX_SECONDS else Kind.LONG


def duration_seconds(value: str) -> int:
    """ISO 8601: PT1M5S, PT2H, P1DT3M; у эфиров бывает P0D. Не разобралось — 0."""
    match = DURATION.fullmatch(value or "")
    if not match:
        return 0
    return sum(int(part or 0) * seconds for part, seconds in zip(match.groups(), SECONDS_IN))


def usable(videos: list[Video]) -> list[Video]:
    """Без ещё не вышедших и идущих сейчас эфиров, новые — первыми (ТЗ, 6.0)."""
    done = [video for video in videos if video.broadcast == NOT_A_BROADCAST]
    return sorted(done, key=lambda video: video.published, reverse=True)
