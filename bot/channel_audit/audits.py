"""Аудиты в базе (ТЗ, раздел 12): кто, откуда, чем кончилось, списано ли, сколько единиц квоты.

Из данных YouTube здесь только channel_id и handle — их обнуляет уборка через 20 дней (bot/maintenance.py). @имя
хранится в нижнем регистре: /channel ищет его без учёта регистра (ТЗ, раздел 8). Человек должен быть в users до
записи аудита — внешний ключ; Users.touch — обязанность вызывающего, как у чекера. Статусы идут в SQL только
параметрами — литералов вроде 'running' в запросах нет.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.core.clock import Clock, from_iso, to_iso

RUNNING = "running"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"
RECENT_LIMIT = 5

INSERT_AUDIT = """
INSERT INTO audits (user_id, source, input_kind, status, error_code, chat_id, message_id, created_at)
VALUES (:user_id, :source, :input_kind, :status, :error_code, :chat_id, :message_id, :now) RETURNING id"""
FINISH = """
UPDATE audits SET status = :status, error_code = :error_code, channel_id = :channel_id, handle = :handle,
  from_cache = :from_cache, charged = :charged, api_units = :api_units, offered = :offered,
  message_id = COALESCE(:message_id, message_id), finished_at = :now
WHERE id = :id"""
COUNT_CHARGED = "SELECT COUNT(*) FROM audits WHERE charged = 1 AND created_at >= :since AND user_id = :user_id"
OLDEST_CHARGED = "SELECT MIN(created_at) FROM audits WHERE charged = 1 AND created_at >= :since AND user_id = :user_id"
COUNT_GOOGLE = "SELECT COUNT(*) FROM audits WHERE api_units > 0 AND created_at >= :since"
OLDEST_GOOGLE = "SELECT MIN(created_at) FROM audits WHERE api_units > 0 AND created_at >= :since"
UNFINISHED = """
SELECT audits.id, audits.chat_id, audits.message_id, users.lang FROM audits JOIN users USING (user_id)
WHERE audits.status = :running AND audits.message_id IS NOT NULL"""
INTERRUPT = """
UPDATE audits SET status = :interrupted, error_code = :interrupted, charged = 0, finished_at = :now
WHERE status = :running"""
RECENT_FOR_CHANNEL = """
SELECT created_at, source, status, error_code, from_cache, offered FROM audits
WHERE (channel_id = :channel_id OR handle = :handle) AND created_at >= :since
ORDER BY created_at DESC, id DESC LIMIT :limit"""
STATS_BY_SOURCE = """
SELECT source, COUNT(*) AS audits, COUNT(DISTINCT CASE WHEN status = :done THEN user_id END) AS reported_users,
  SUM(from_cache) AS from_cache, SUM(offered) AS offered,
  SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS refusals
FROM audits WHERE created_at >= :since GROUP BY source"""
NEW_USERS_BY_SOURCE = """
SELECT first_source AS source, COUNT(*) AS new_users FROM users WHERE created_at >= :since GROUP BY first_source"""
REFUSALS_BY_CODE = """
SELECT error_code, COUNT(*) AS total FROM audits WHERE created_at >= :since AND error_code IS NOT NULL
GROUP BY error_code ORDER BY total DESC, error_code"""
FORGET_AUDITS = "DELETE FROM audits WHERE user_id = :user_id"
FORGET_USER = "DELETE FROM users WHERE user_id = :user_id"


@dataclass(frozen=True)
class NewAudit:
    user_id: int
    source: str
    input_kind: str | None
    status: str
    error_code: str | None = None
    chat_id: int | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class Closing:
    """Чем кончился аудит — одной записью (ТЗ, раздел 12)."""

    status: str
    error_code: str | None = None
    channel_id: str | None = None
    handle: str | None = None
    from_cache: bool = False
    charged: bool = False
    api_units: int = 0
    offered: bool = False
    message_id: int | None = None  # где теперь отчёт: мог уйти новым сообщением


@dataclass(frozen=True)
class Unfinished:
    audit_id: int
    chat_id: int
    message_id: int
    lang: str


@dataclass(frozen=True)
class ChannelAudit:
    created_at: datetime
    source: str
    status: str
    error_code: str | None
    from_cache: bool
    offered: bool


@dataclass(frozen=True)
class LabelStats:
    source: str
    new_users: int
    reported_users: int
    audits: int
    from_cache: int
    offered: int
    refusals: int


class AuditsRepo:
    def __init__(self, engine: AsyncEngine, clock: Clock):
        self._engine = engine
        self._clock = clock

    def _now(self) -> str:
        return to_iso(self._clock.now())

    async def _scalar(self, sql: str, params: dict[str, Any]) -> Any:
        async with self._engine.connect() as connection:
            return (await connection.execute(text(sql), params)).scalar()

    async def create(self, new: NewAudit) -> int:
        params = {"user_id": new.user_id, "source": new.source, "input_kind": new.input_kind, "status": new.status,
                  "error_code": new.error_code, "chat_id": new.chat_id, "message_id": new.message_id,
                  "now": self._now()}
        async with self._engine.begin() as connection:
            return (await connection.execute(text(INSERT_AUDIT), params)).scalar_one()

    async def finish(self, audit_id: int, closing: Closing) -> None:
        params = {"id": audit_id, "now": self._now(), "status": closing.status, "error_code": closing.error_code,
                  "channel_id": closing.channel_id, "handle": closing.handle.lower() if closing.handle else None,
                  "from_cache": int(closing.from_cache), "charged": int(closing.charged),
                  "api_units": closing.api_units, "offered": int(closing.offered), "message_id": closing.message_id}
        async with self._engine.begin() as connection:
            await connection.execute(text(FINISH), params)

    async def count_charged_since(self, since: datetime, user_id: int) -> int:
        return await self._scalar(COUNT_CHARGED, {"since": to_iso(since), "user_id": user_id})

    async def oldest_charged_since(self, since: datetime, user_id: int) -> datetime | None:
        return _moment(await self._scalar(OLDEST_CHARGED, {"since": to_iso(since), "user_id": user_id}))

    async def count_google_since(self, since: datetime) -> int:
        return await self._scalar(COUNT_GOOGLE, {"since": to_iso(since)})

    async def oldest_google_since(self, since: datetime) -> datetime | None:
        return _moment(await self._scalar(OLDEST_GOOGLE, {"since": to_iso(since)}))

    async def interrupt_unfinished(self) -> list[Unfinished]:
        async with self._engine.begin() as connection:
            rows = (await connection.execute(text(UNFINISHED), {"running": RUNNING})).all()
            await connection.execute(text(INTERRUPT), {"running": RUNNING, "interrupted": INTERRUPTED,
                                                       "now": self._now()})
        return [Unfinished(row.id, row.chat_id, row.message_id, row.lang) for row in rows]

    async def recent_for_channel(self, channel_id: str | None, handle: str | None,
                                 since: datetime) -> list[ChannelAudit]:
        params = {"channel_id": channel_id, "handle": handle.lower() if handle else None, "since": to_iso(since),
                  "limit": RECENT_LIMIT}
        async with self._engine.connect() as connection:
            rows = (await connection.execute(text(RECENT_FOR_CHANNEL), params)).all()
        return [ChannelAudit(from_iso(row.created_at), row.source, row.status, row.error_code, bool(row.from_cache),
                             bool(row.offered)) for row in rows]

    async def stats(self, since: datetime) -> tuple[list[LabelStats], list[tuple[str, int]]]:
        params = {"since": to_iso(since)}
        async with self._engine.connect() as connection:
            by_source = (await connection.execute(text(STATS_BY_SOURCE), {**params, "done": DONE})).all()
            new_users = dict((await connection.execute(text(NEW_USERS_BY_SOURCE), params)).all())
            refusals = [(row.error_code, row.total) for row in await connection.execute(text(REFUSALS_BY_CODE), params)]
        return _label_stats(by_source, new_users), refusals

    async def forget_user(self, user_id: int) -> int:
        """Удаление по просьбе человека (ТЗ, Ю13): его аудиты и сам он. Возвращает число удалённых аудитов."""
        async with self._engine.begin() as connection:
            audits = (await connection.execute(text(FORGET_AUDITS), {"user_id": user_id})).rowcount
            await connection.execute(text(FORGET_USER), {"user_id": user_id})
        return audits


def _moment(value: str | None) -> datetime | None:
    return from_iso(value) if value else None


def _label_stats(by_source, new_users: dict[str, int]) -> list[LabelStats]:
    rows = {row.source: row for row in by_source}
    return [_label_row(label, rows.get(label), new_users.get(label, 0)) for label in sorted(set(rows) | set(new_users))]


def _label_row(label: str, row, new_users: int) -> LabelStats:
    if row is None:
        return LabelStats(label, new_users, 0, 0, 0, 0, 0)
    return LabelStats(label, new_users, row.reported_users, row.audits, row.from_cache, row.offered, row.refusals)
