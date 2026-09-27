"""Уведомления владельцу (ТЗ, 7.4, раздел 8): у каждого вида — своя пауза, чтобы не засыпать личку.

Время последнего уведомления каждого вида — в kv: перезапуск контейнера паузу не сбрасывает. Сбой базы — пауза
держится в памяти процесса (Р16).
"""
from datetime import datetime, timedelta

from loguru import logger

from bot.channel_audit.kv import Kv
from bot.core.clock import Clock, from_iso, to_iso
from bot.core.commands import Brand, simple_message
from bot.core.i18n import Lang, Texts
from bot.core.messenger import DeliveryFailed, Messenger
from bot.core.stats import best_effort

OWNER_LANG: Lang = "ru"
DAY = timedelta(days=1)
SIX_HOURS = timedelta(hours=6)
OWNER_TIME_FORMAT = "%d.%m %H:%M"  # время для владельца — по UTC+7, как даты отчёта
KEY_PREFIX = "notify:"
WHAT = "время уведомления владельцу"


class Notifier:
    def __init__(self, messenger: Messenger, admin_id: int, clock: Clock, texts: Texts, brand: Brand, kv: Kv):
        self._messenger = messenger
        self._admin_id = admin_id
        self._clock = clock
        self._texts = texts
        self._brand = brand
        self._kv = kv
        self._last: dict[str, datetime] = {}

    async def notify(self, kind: str, key: str, period: timedelta, **params: object) -> None:
        now = self._clock.now()
        if await self._within(kind, period, now):
            return
        await self._mark(kind, now)
        # То же служебное сообщение, что и у остальных команд, — не своя копия сборки.
        message = simple_message(self._texts, OWNER_LANG, self._texts.get(OWNER_LANG, key, **params), self._brand)
        try:
            await self._messenger.send(self._admin_id, message)
        except DeliveryFailed as error:
            logger.warning("уведомление владельцу не ушло: {}", error)

    async def _within(self, kind: str, period: timedelta, now: datetime) -> bool:
        last = self._last.get(kind)
        if last is None:
            stored = await best_effort(self._kv.get(KEY_PREFIX + kind), WHAT, None)
            last = from_iso(stored) if stored else None
        return last is not None and now - last < period

    async def _mark(self, kind: str, now: datetime) -> None:
        self._last[kind] = now
        await best_effort(self._kv.set(KEY_PREFIX + kind, to_iso(now)), WHAT, None)
