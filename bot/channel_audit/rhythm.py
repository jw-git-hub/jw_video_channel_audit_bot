"""Ритм (ТЗ, 6.1): сколько видео за охват и в среднем в месяц, последнее видео, перерывы дольше 45 дней.

Охват — от самого раннего собранного видео до сегодня, но не больше полугода. Короче полугода он бывает, когда
листание упёрлось в 200 видео (у канала 2–3 видео в день) или канал моложе: тогда «200 видео с 12 июля», а не
«за полгода». Перерывы — только внутри охвата и только между двумя собранными видео.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bot.channel_audit.thresholds import AVERAGE_MONTH_DAYS, GAP_DAYS, RHYTHM_DAYS, RHYTHM_MONTHS
from bot.channel_audit.videos import Video
from bot.channel_audit.wording import local_date

MIN_MONTHS = 1


@dataclass(frozen=True)
class Gap:
    days: int
    start: date
    end: date | None  # None — перерыв длится до сегодня


@dataclass(frozen=True)
class Rhythm:
    since: datetime  # начало охвата
    count: int  # видео за охват, все виды
    partial_since: date | None  # охват короче полугода — с этой даты; None — полные полгода
    per_month: float
    last_published: date
    last_age_days: int
    gap_to_now: Gap | None
    past_gap: Gap | None

    @property
    def quiet(self) -> bool:
        """За полгода видео не было — перерывы не показываются."""
        return self.count == 0


def rhythm(videos: list[Video], now: datetime) -> Rhythm:
    """videos — из usable(): новые первыми, не пусто."""
    window_start = now - timedelta(days=RHYTHM_DAYS)
    earliest, last = videos[-1].published, videos[0].published
    partial = earliest > window_start
    since = earliest if partial else window_start
    count = sum(1 for video in videos if video.published >= since)
    gaps = (_gap_to_now(last, now), _longest_past_gap(videos, since)) if count else (None, None)
    return Rhythm(since, count, local_date(earliest) if partial else None, count / _months(since, now, partial),
                  local_date(last), (now - last).days, *gaps)


def _months(since: datetime, now: datetime, partial: bool) -> float:
    if not partial:
        return RHYTHM_MONTHS
    return max(MIN_MONTHS, (now - since).days / AVERAGE_MONTH_DAYS)


def _gap_to_now(last: datetime, now: datetime) -> Gap | None:
    days = (now - last).days
    return Gap(days, local_date(last), None) if days > GAP_DAYS else None


def _longest_past_gap(videos: list[Video], since: datetime) -> Gap | None:
    """Между соседними собранными видео, если более позднее — в охвате. Показывается один, самый длинный."""
    gaps = [Gap((newer.published - older.published).days, local_date(older.published), local_date(newer.published))
            for newer, older in zip(videos, videos[1:]) if newer.published >= since]
    return max((gap for gap in gaps if gap.days > GAP_DAYS), key=lambda gap: gap.days, default=None)
