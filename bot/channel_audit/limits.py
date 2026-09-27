"""Лимиты (ТЗ, Л3, Л4, Л8): списанные попытки человека и аудиты с походом в Google — за скользящие 24 часа;
владельцу — без лимита. Считает база; недоступна — счёт в памяти: теряется точность, а не аудит (Р16)."""
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from bot.channel_audit.audits import AuditsRepo
from bot.core.clock import Clock

WINDOW = timedelta(hours=24)
MIN_WAIT = timedelta(hours=1)
SECONDS_IN_HOUR = 3600
MIN_HOURS_LEFT = 1
LIMIT_USER = "limit_user"
LIMIT_GLOBAL = "limit_global"


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    code: str | None = None
    reopens_at: datetime | None = None  # когда освободится место: самая старая попытка в окне + 24 часа


ALLOWED = LimitDecision(True)


@dataclass(frozen=True)
class Spent:
    """Попытка в памяти — на случай сбоя базы."""

    moment: datetime
    user_id: int
    charged: bool
    used_google: bool


@dataclass(frozen=True)
class Counts:
    mine: int
    oldest_mine: datetime | None
    google: int
    oldest_google: datetime | None


def hours_until(moment: datetime, now: datetime) -> int:
    """Целых часов до момента — вверх и не меньше одного: «через 23 ч»."""
    return max(MIN_HOURS_LEFT, math.ceil((moment - now).total_seconds() / SECONDS_IN_HOUR))


class Limits:
    def __init__(self, repo: AuditsRepo, clock: Clock, user_daily: int, global_daily: int, admin_id: int):
        self._repo = repo
        self._clock = clock
        self.user_daily = user_daily
        self.global_daily = global_daily
        self._admin_id = admin_id
        self._memory: deque[Spent] = deque()

    def remember(self, user_id: int, charged: bool, used_google: bool) -> None:
        """Итог каждого аудита — в память; обрезка здесь же, иначе при исправной базе память росла бы всегда."""
        now = self._clock.now()
        self._forget_before(now - WINDOW)
        if charged or used_google:
            self._memory.append(Spent(now, user_id, charged, used_google))

    async def decide(self, user_id: int, uses_google: bool) -> LimitDecision:
        """uses_google — канала нет в кэше: отчёты из кэша в общий потолок не входят (ТЗ, Л4)."""
        if user_id == self._admin_id:
            return ALLOWED
        counts = await self._counts(user_id, self._clock.now() - WINDOW)
        if counts.mine >= self.user_daily:
            return LimitDecision(False, LIMIT_USER, self._reopens(counts.oldest_mine))
        if uses_google and counts.google >= self.global_daily:
            return LimitDecision(False, LIMIT_GLOBAL, self._reopens(counts.oldest_google))
        return ALLOWED

    async def _counts(self, user_id: int, since: datetime) -> Counts:
        try:
            return Counts(await self._repo.count_charged_since(since, user_id),
                          await self._repo.oldest_charged_since(since, user_id),
                          await self._repo.count_google_since(since), await self._repo.oldest_google_since(since))
        except Exception:  # noqa: BLE001 — база недоступна: лимиты по памяти (ТЗ, Л8)
            logger.warning("лимиты считаются в памяти: база недоступна")
            return self._memory_counts(user_id, since)

    def _memory_counts(self, user_id: int, since: datetime) -> Counts:
        self._forget_before(since)
        mine = [item.moment for item in self._memory if item.user_id == user_id and item.charged]
        google = [item.moment for item in self._memory if item.used_google]
        return Counts(len(mine), mine[0] if mine else None, len(google), google[0] if google else None)

    def _forget_before(self, since: datetime) -> None:
        while self._memory and self._memory[0].moment < since:
            self._memory.popleft()

    def _reopens(self, oldest: datetime | None) -> datetime:
        return oldest + WINDOW if oldest else self._clock.now() + MIN_WAIT
