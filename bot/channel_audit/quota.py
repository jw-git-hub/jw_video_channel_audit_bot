"""Свой потолок расхода квоты YouTube (ТЗ, Л9): единицы за сутки по тихоокеанскому времени, по счётчику бота.

Квота Google обнуляется в полночь по тихоокеанскому времени (14:00–15:00 по UTC+7). Дошли до своего потолка или
Google ответил quotaExceeded — до этой полуночи бот в Google не ходит. Счётчик лежит в kv: перезапуск контейнера
сутки не обнуляет. Сбой базы — счёт идёт в памяти (ТЗ, Р16).
"""
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bot.channel_audit.kv import Kv
from bot.core.clock import Clock
from bot.core.stats import best_effort

PACIFIC = ZoneInfo("America/Los_Angeles")
DAY_KEY = "quota:day"
UNITS_KEY = "quota:units"
EXHAUSTED_KEY = "quota:exhausted"
QUOTA = "quota"
CEILING = "ceiling"
SECONDS_IN_HOUR = 3600
MIN_HOURS = 1
WHAT = "счётчик квоты"


def pacific_day(moment: datetime) -> date:
    return moment.astimezone(PACIFIC).date()


def hours_until_reset(moment: datetime) -> int:
    local = moment.astimezone(PACIFIC)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(), PACIFIC)
    return max(MIN_HOURS, math.ceil((midnight - local).total_seconds() / SECONDS_IN_HOUR))


class QuotaGate:
    def __init__(self, kv: Kv, clock: Clock, ceiling: int):
        self._kv = kv
        self._clock = clock
        self._ceiling = ceiling
        self._day = pacific_day(clock.now())
        self._units = 0
        self._exhausted = False

    @property
    def ceiling(self) -> int:
        return self._ceiling

    async def load(self) -> None:
        """Сегодняшний счёт из kv; вчерашний не в счёт."""
        self._day, self._units, self._exhausted = pacific_day(self._clock.now()), 0, False
        today = self._day.isoformat()
        if await best_effort(self._kv.get(DAY_KEY), WHAT, None) != today:
            return
        self._units = int(await best_effort(self._kv.get(UNITS_KEY), WHAT, None) or 0)
        self._exhausted = await best_effort(self._kv.get(EXHAUSTED_KEY), WHAT, None) == today

    def block_reason(self) -> str | None:
        """QUOTA — Google сказал quotaExceeded; CEILING — свой потолок; None — в Google можно."""
        self._roll_day()
        if self._exhausted:
            return QUOTA
        return CEILING if self._units >= self._ceiling else None

    def units_today(self) -> int:
        self._roll_day()
        return self._units

    def hours_left(self) -> int:
        return hours_until_reset(self._clock.now())

    async def spend(self, units: int) -> None:
        self._roll_day()
        self._units += units
        await self._save(UNITS_KEY, str(self._units))

    async def exhaust(self) -> None:
        self._roll_day()
        self._exhausted = True
        await self._save(EXHAUSTED_KEY, self._day.isoformat())

    def _roll_day(self) -> None:
        today = pacific_day(self._clock.now())
        if today != self._day:
            self._day, self._units, self._exhausted = today, 0, False

    async def _save(self, key: str, value: str) -> None:
        await best_effort(self._kv.set(DAY_KEY, self._day.isoformat()), WHAT, None)
        await best_effort(self._kv.set(key, value), WHAT, None)
