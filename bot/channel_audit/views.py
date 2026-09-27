"""Отдача (ТЗ, 6.2): «обычно» и «последние 10» по группам, лучшее видео за полгода и отношение к обычному.

Считаются видео за год, без свежих: коротким хватает двух недель, длинным и эфирам — 60 дней, им просмотры
месяцами приносят поиск и рекомендации. Группы — отдельно: у коротких просмотры считаются с каждого запуска.
«Обычно» — медиана группы, подписанная в отчёте как свой подсчёт; никаких оценок каналу (ТЗ, Ю2).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from bot.channel_audit.thresholds import (BASELINE_DAYS, BEST_RATIO_MIN, FRESH_DAYS_LONG, FRESH_DAYS_SHORT,
                                          MIN_TREND, MIN_TYPICAL, RECENT_COUNT, RHYTHM_DAYS)
from bot.channel_audit.videos import Kind, Video
from bot.channel_audit.wording import round_half_up

GROUP_ORDER = (Kind.SHORT, Kind.LONG, Kind.LIVE)
FRESH_DAYS = {Kind.SHORT: FRESH_DAYS_SHORT, Kind.LONG: FRESH_DAYS_LONG, Kind.LIVE: FRESH_DAYS_LONG}
MIN_RATIO_BASE = 1  # «обычно» меньше одного просмотра — отношения нет (деление на ноль)


@dataclass(frozen=True)
class BestVideo:
    video_id: str
    title: str
    views: int
    ratio: int | None


@dataclass(frozen=True)
class GroupViews:
    kind: Kind
    typical: float
    recent: float | None
    best: BestVideo | None


def views_by_group(videos: list[Video], now: datetime) -> tuple[GroupViews, ...]:
    """videos — из usable(): новые первыми. Только группы, где набралось «обычно»."""
    groups = (_group(kind, _eligible(videos, kind, now), now) for kind in GROUP_ORDER)
    return tuple(group for group in groups if group is not None)


def _eligible(videos: list[Video], kind: Kind, now: datetime) -> list[Video]:
    oldest, newest = now - timedelta(days=BASELINE_DAYS), now - timedelta(days=FRESH_DAYS[kind])
    return [video for video in videos
            if video.kind == kind and video.views is not None and oldest <= video.published <= newest]


def _group(kind: Kind, eligible: list[Video], now: datetime) -> GroupViews | None:
    if len(eligible) < MIN_TYPICAL:
        return None
    typical = median(video.views for video in eligible)
    recent = median(video.views for video in eligible[:RECENT_COUNT]) if len(eligible) >= MIN_TREND else None
    return GroupViews(kind, typical, recent, _best(eligible, typical, now))


def _best(eligible: list[Video], typical: float, now: datetime) -> BestVideo | None:
    half_year = now - timedelta(days=RHYTHM_DAYS)
    candidates = [video for video in eligible if video.published >= half_year]
    if not candidates:
        return None
    top = max(candidates, key=lambda video: video.views)
    return BestVideo(top.video_id, top.title, top.views, _ratio(top.views, typical))


def _ratio(views: int, typical: float) -> int | None:
    if typical < MIN_RATIO_BASE:
        return None
    ratio = int(round_half_up(views / typical))
    return ratio if ratio >= BEST_RATIO_MIN else None
