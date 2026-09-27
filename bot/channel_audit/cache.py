"""Кэш на сутки в памяти (ТЗ, 5.2): «что прислали → ID канала» и «ID канала → факты отчёта».

В базу кэш не пишется. При перезапуске он пуст — это нормально. Старые записи вытесняются, когда их больше 500.
"""
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from bot.channel_audit.input import CHANNEL_ID, VIDEO, Target
from bot.core.clock import Clock

TTL = timedelta(days=1)
MAX_ITEMS = 500
CASE_SENSITIVE_KINDS = frozenset({CHANNEL_ID, VIDEO})
BARE_SUFFIX = "-bare"
Value = TypeVar("Value")


def target_key(target: Target) -> str:
    """@имя и старое имя — без учёта регистра, ID канала и видео — с учётом (ТЗ, 5.2)."""
    value = target.value if target.kind in CASE_SENSITIVE_KINDS else target.value.lower()
    return f"{target.kind}{BARE_SUFFIX if target.bare else ''}:{value}"


class DayCache(Generic[Value]):
    def __init__(self, clock: Clock, ttl: timedelta = TTL, max_items: int = MAX_ITEMS):
        self._clock = clock
        self._ttl = ttl
        self._max_items = max_items
        self._items: OrderedDict[str, tuple[datetime, Value]] = OrderedDict()

    def get(self, key: str) -> Value | None:
        stored = self._items.get(key)
        if stored is None:
            return None
        saved_at, value = stored
        if self._clock.now() - saved_at > self._ttl:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: Value) -> None:
        self._items[key] = (self._clock.now(), value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)
