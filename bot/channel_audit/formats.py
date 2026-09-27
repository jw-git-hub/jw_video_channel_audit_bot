"""Форматы (ТЗ, 6.3): сколько коротких (до 3 минут), длинных и эфиров за охват ритма."""
from dataclasses import dataclass
from datetime import datetime

from bot.channel_audit.videos import Kind, Video


@dataclass(frozen=True)
class Formats:
    short: int
    long: int
    live: int

    def counts(self) -> dict[Kind, int]:
        return {Kind.SHORT: self.short, Kind.LONG: self.long, Kind.LIVE: self.live}


def formats(videos: list[Video], since: datetime) -> Formats | None:
    """None — за охват видео не было, блока нет."""
    kinds = [video.kind for video in videos if video.published >= since]
    if not kinds:
        return None
    return Formats(kinds.count(Kind.SHORT), kinds.count(Kind.LONG), kinds.count(Kind.LIVE))
