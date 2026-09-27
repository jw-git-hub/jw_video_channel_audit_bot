"""Один аудит целиком (ТЗ, разделы 5–6, Л5): кэш → поиск канала → видео → факты; ошибки — в коды ответа."""
from dataclasses import dataclass

from bot.channel_audit.cache import DayCache, target_key
from bot.channel_audit.collect import ChannelNotFound, Collector
from bot.channel_audit.facts import Facts, build_facts
from bot.channel_audit.input import LEGACY, VIDEO, Target
from bot.channel_audit.youtube import Meter, QuotaExhausted, ServiceDown
from bot.core.clock import Clock

NOT_FOUND = "not_found"
LEGACY_NOT_FOUND = "legacy_not_found"
VIDEO_NOT_FOUND = "video_not_found"
QUOTA = "quota"
SERVICE_DOWN = "service_down"
NOT_FOUND_CODES = {LEGACY: LEGACY_NOT_FOUND, VIDEO: VIDEO_NOT_FOUND}
CHARGED_CODES = frozenset({NOT_FOUND, LEGACY_NOT_FOUND, VIDEO_NOT_FOUND})


@dataclass(frozen=True)
class AuditOutcome:
    facts: Facts | None = None
    error_code: str | None = None
    from_cache: bool = False
    units: int = 0
    reason: str | None = None  # причина сбоя сервиса или блокировки квоты — для уведомления владельцу

    @property
    def charged(self) -> bool:
        """Списывается отчёт и «нет такого» на присланное (ТЗ, Л5)."""
        return self.facts is not None or self.error_code in CHARGED_CODES


class Auditor:
    def __init__(self, collector: Collector, targets: DayCache[str], facts: DayCache[Facts], clock: Clock):
        self._collector = collector
        self._targets = targets
        self._facts = facts
        self._clock = clock

    def cached(self, target: Target) -> Facts | None:
        channel_id = self._targets.get(target_key(target))
        return self._facts.get(channel_id) if channel_id else None

    async def run(self, target: Target, deadline: float, meter: Meter) -> AuditOutcome:
        known = self.cached(target)
        if known is not None:
            return AuditOutcome(known, from_cache=True)
        try:
            facts, from_cache = await self._collect(target, deadline, meter)
        except ChannelNotFound as missing:
            return AuditOutcome(error_code=NOT_FOUND_CODES.get(missing.args[0], NOT_FOUND), units=meter.units)
        except QuotaExhausted as blocked:
            return AuditOutcome(error_code=QUOTA, units=meter.units, reason=blocked.reason)
        except ServiceDown as down:
            return AuditOutcome(error_code=SERVICE_DOWN, units=meter.units, reason=down.reason)
        return AuditOutcome(facts, from_cache=from_cache, units=meter.units)

    async def _collect(self, target: Target, deadline: float, meter: Meter) -> tuple[Facts, bool]:
        channel = await self._collector.find_channel(target, deadline, meter)
        self._targets.put(target_key(target), channel.channel_id)
        known = self._facts.get(channel.channel_id)
        if known is not None:
            return known, True
        videos = await self._collector.videos(channel.uploads, deadline, meter)
        facts = build_facts(channel, videos, self._clock.now())
        self._facts.put(channel.channel_id, facts)
        return facts, False
