"""Команды владельца (ТЗ, раздел 8): /stats — учёт по меткам и расход квоты, /channel — кто и когда смотрел канал,
/forget — удалить данные человека по его просьбе (ТЗ, Ю13).

/channel ищет только по базе — по @имени без учёта регистра или по ID канала — и в Google не ходит. Сам отчёт
владелец видит, прислав тот же канал: сутки он придёт из кэша таким же, каким его видел человек.
"""
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message
from loguru import logger

from bot.channel_audit.audits import AuditsRepo, ChannelAudit, LabelStats
from bot.channel_audit.input import CHANNEL_ID, HANDLE, Target, parse_input
from bot.channel_audit.notifier import OWNER_LANG, OWNER_TIME_FORMAT
from bot.channel_audit.quota import QuotaGate
from bot.channel_audit.report import SECTION_SIZE
from bot.channel_audit.thresholds import API_DATA_DAYS
from bot.channel_audit.wording import DISPLAY_TIMEZONE
from bot.core import rich
from bot.core.clock import Clock
from bot.core.commands import Brand, page_header, simple_message
from bot.core.config import CoreSettings
from bot.core.i18n import Texts
from bot.core.messenger import Messenger

STATS_WINDOWS_DAYS = (7, 30)
STATS_COLUMNS = ("stats_label", "stats_new", "stats_reported", "stats_audits", "stats_cache", "stats_offered",
                 "stats_refusals")
CHANNEL_COLUMNS = ("channel_when", "channel_source", "channel_result", "channel_cache", "channel_offered")
ITEMS_JOIN = ", "
HANDLE_MARK = "@"

router = Router(name="admin")

Window = tuple[int, list[LabelStats], list[tuple[str, int]]]


class IsAdmin(Filter):
    async def __call__(self, event: Message, settings: CoreSettings) -> bool:
        return event.from_user is not None and event.from_user.id == settings.admin_id


@dataclass(frozen=True)
class ChannelQuery:
    """Что искать в базе: ID канала или @имя — с «@» и в нижнем регистре, как его хранит audits.py."""

    channel_id: str | None
    handle: str | None


def channel_query(args: str) -> ChannelQuery | None:
    parsed = parse_input(args, [])
    if isinstance(parsed, Target) and parsed.kind == HANDLE:
        return ChannelQuery(None, HANDLE_MARK + parsed.value.lower())
    if isinstance(parsed, Target) and parsed.kind == CHANNEL_ID:
        return ChannelQuery(parsed.value, None)
    return None


@router.message(Command("stats"), IsAdmin())
async def on_stats(message: Message, repo: AuditsRepo, quota: QuotaGate, messenger: Messenger, texts: Texts,
                   brand: Brand, clock: Clock) -> None:
    windows = [(days, *await repo.stats(clock.now() - timedelta(days=days))) for days in STATS_WINDOWS_DAYS]
    await messenger.send(message.chat.id, stats_message(texts, brand, windows, quota))


@router.message(Command("channel"), IsAdmin())
async def on_channel(message: Message, command: CommandObject, repo: AuditsRepo, messenger: Messenger, texts: Texts,
                     brand: Brand, clock: Clock) -> None:
    query = channel_query(command.args or "")
    if query is None:
        await messenger.send(message.chat.id, _owner_text(texts, brand, "channel_usage"))
        return
    since = clock.now() - timedelta(days=API_DATA_DAYS)
    audits = await repo.recent_for_channel(query.channel_id, query.handle, since)
    await messenger.send(message.chat.id, channel_message(texts, brand, query.handle or query.channel_id, audits))


@router.message(Command("forget"), IsAdmin())
async def on_forget(message: Message, command: CommandObject, repo: AuditsRepo, messenger: Messenger, texts: Texts,
                    brand: Brand) -> None:
    user_id = _telegram_id(command.args)
    if user_id is None:
        await messenger.send(message.chat.id, _owner_text(texts, brand, "forget_usage"))
        return
    count = await repo.forget_user(user_id)
    logger.info("данные человека удалены по просьбе, аудитов: {}", count)  # в журнал — только факт (ТЗ, раздел 8)
    await messenger.send(message.chat.id, _owner_text(texts, brand, "forget_done", user_id=user_id, count=count))


def stats_message(texts: Texts, brand: Brand, windows: list[Window], quota: QuotaGate) -> dict:
    blocks = [page_header(texts, OWNER_LANG, brand)]
    for days, rows, refusals in windows:
        blocks += _stats_section(texts, days, rows, refusals)
    units = texts.get(OWNER_LANG, "stats_units", units=quota.units_today(), ceiling=quota.ceiling)
    return rich.message([*blocks, rich.paragraph(units), rich.paragraph(texts.get(OWNER_LANG, "stats_note"))])


def _stats_section(texts: Texts, days: int, rows: list[LabelStats], refusals: list[tuple[str, int]]) -> list[dict]:
    days_text = texts.count(OWNER_LANG, days, "day")
    title = rich.heading(texts.get(OWNER_LANG, "stats_title", days=days_text), SECTION_SIZE)
    if not rows:
        return [title, rich.paragraph(texts.get(OWNER_LANG, "stats_empty"))]
    header = [texts.get(OWNER_LANG, key) for key in STATS_COLUMNS]
    section = [title, rich.table([header, *(_stats_row(row) for row in rows)])]
    if refusals:
        items = ITEMS_JOIN.join(f"{code} — {total}" for code, total in refusals)
        section.append(rich.paragraph(texts.get(OWNER_LANG, "stats_refusal_codes", items=items)))
    return section


def _stats_row(row: LabelStats) -> list[str]:
    numbers = (row.new_users, row.reported_users, row.audits, row.from_cache, row.offered, row.refusals)
    return [row.source, *(str(number) for number in numbers)]


def channel_message(texts: Texts, brand: Brand, name: str, audits: list[ChannelAudit]) -> dict:
    blocks = [page_header(texts, OWNER_LANG, brand),
              rich.heading(texts.get(OWNER_LANG, "channel_title", channel=name), SECTION_SIZE)]
    if not audits:
        days = texts.count(OWNER_LANG, API_DATA_DAYS, "day")
        return rich.message([*blocks, rich.paragraph(texts.get(OWNER_LANG, "channel_empty", days=days))])
    header = [texts.get(OWNER_LANG, key) for key in CHANNEL_COLUMNS]
    return rich.message([*blocks, rich.table([header, *(_channel_row(texts, audit) for audit in audits)])])


def _channel_row(texts: Texts, audit: ChannelAudit) -> list[str]:
    when = audit.created_at.astimezone(DISPLAY_TIMEZONE).strftime(OWNER_TIME_FORMAT)
    return [when, audit.source, audit.error_code or audit.status, _yes_no(texts, audit.from_cache),
            _yes_no(texts, audit.offered)]


def _yes_no(texts: Texts, value: bool) -> str:
    return texts.get(OWNER_LANG, "yes" if value else "no")


def _telegram_id(args: str | None) -> int | None:
    value = (args or "").strip()
    return int(value) if value.isdigit() else None


def _owner_text(texts: Texts, brand: Brand, key: str, **params: object) -> dict:
    return simple_message(texts, OWNER_LANG, texts.get(OWNER_LANG, key, **params), brand)
