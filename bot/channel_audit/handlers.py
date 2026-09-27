"""Приём ссылок и аудит (ТЗ, разделы 3, 4, 7.5, 9). Обработчики aiogram — тонкие: работа — в Intake и AuditRunner,
которые знают Telegram только через Messenger.

Очереди нет (Р14): одновременно идут AUDIT_WORKERS аудитов, остальные ждут места внутри срока аудита — 30 секунд
вместе с ожиданием (Л1). У человека один аудит за раз (В8): «занят» проверяется и ставится без await между ними.
"""
import asyncio
import contextlib
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, MessageEntity
from loguru import logger

from bot.channel_audit import replies
from bot.channel_audit.audit import QUOTA, SERVICE_DOWN, AuditOutcome, Auditor
from bot.channel_audit.audits import DONE, FAILED, RUNNING, AuditsRepo, Closing, NewAudit
from bot.channel_audit.input import NOT_YOUTUBE, Rejection, Target, parse_input
from bot.channel_audit.limits import LIMIT_GLOBAL, LIMIT_USER, LimitDecision, Limits, hours_until
from bot.channel_audit.notifier import DAY, OWNER_LANG, OWNER_TIME_FORMAT, SIX_HOURS, Notifier
from bot.channel_audit.quota import CEILING, QuotaGate, hours_until_reset
from bot.channel_audit.report import AGAIN_CALLBACK, build_report
from bot.channel_audit.wording import DISPLAY_TIMEZONE
from bot.channel_audit.youtube import KEY, SHAPE, TOO_LARGE, Meter
from bot.core.clock import Clock
from bot.core.commands import Brand
from bot.core.i18n import Texts
from bot.core.messenger import DeliveryFailed, Messenger, edit_or_send
from bot.core.stats import best_effort
from bot.core.users import User, Users

BUSY = "busy"
NOT_TEXT = "not_text"
CROWDED = "crowded"
BUG = "bug"  # причина: непредвиденное исключение в аудите или в сборке отчёта
DEADLINE = "deadline"  # причина: срок аудита вышел посреди запросов
COMMAND_PREFIX = "/"
AUDIT_SECONDS = 30  # срок аудита вместе с ожиданием места (ТЗ, 5.3, Л1)
RETRY_DELAY_SECONDS = 2  # доставка итога повторяется один раз
DELIVERY_ATTEMPTS = 2
SHAPE_REASONS = frozenset({SHAPE, TOO_LARGE})

router = Router(name="channel_audit")


@dataclass(frozen=True)
class IncomingText:
    user_id: int
    chat_id: int
    language_code: str | None
    text: str
    entity_urls: list[str]


@dataclass(frozen=True)
class Outputs:
    """Куда уходит результат: человеку, владельцу, в учёт; тексты и оформление."""

    messenger: Messenger
    notifier: Notifier
    repo: AuditsRepo
    texts: Texts
    brand: Brand


@dataclass
class Job:
    audit_id: int | None
    user: User
    chat_id: int
    message_id: int
    target: Target
    deadline: float  # момент clock.monotonic(), к которому аудит кончается


def entity_urls(message_text: str, entities: list[MessageEntity]) -> list[str]:
    urls = []
    for entity in entities:
        if entity.type == "text_link" and entity.url:
            urls.append(entity.url)
        elif entity.type == "url":
            urls.append(entity.extract_from(message_text))
    return urls


def incoming_from(message: Message) -> IncomingText:
    message_text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    return IncomingText(message.from_user.id, message.chat.id, message.from_user.language_code, message_text,
                        entity_urls(message_text, entities))


def closing(job: Job, outcome: AuditOutcome) -> Closing:
    """Запись итога: из данных YouTube — только ID и @имя канала (ТЗ, раздел 12)."""
    facts = outcome.facts
    if facts is None:
        return Closing(FAILED, outcome.error_code, from_cache=outcome.from_cache, charged=outcome.charged,
                       api_units=outcome.units, message_id=job.message_id)
    offered = facts.ending is not None and facts.ending.active
    return Closing(DONE, None, facts.channel_id, facts.handle, outcome.from_cache, outcome.charged, outcome.units,
                   offered, job.message_id)


class AuditRunner:
    """«Смотрю канал…» → место → аудит → отчёт правкой того же сообщения → учёт → уведомления владельцу."""

    def __init__(self, outputs: Outputs, auditor: Auditor, limits: Limits, quota: QuotaGate,
                 slots: asyncio.Semaphore, clock: Clock, audit_seconds: float = AUDIT_SECONDS):
        self._out = outputs
        self._texts, self._brand = outputs.texts, outputs.brand
        self._auditor = auditor
        self._limits = limits
        self._quota = quota
        self._slots = slots
        self._clock = clock
        self._audit_seconds = audit_seconds

    async def run(self, chat_id: int, user: User, target: Target) -> None:
        deadline = self._clock.monotonic() + self._audit_seconds
        try:
            message_id = await self._out.messenger.send(chat_id, replies.checking(self._texts, user.lang, self._brand))
        except DeliveryFailed as error:
            logger.warning("«Смотрю канал…» не доставлено, аудит не начат: {}", error)
            return
        new = NewAudit(user.user_id, user.last_source, target.kind, RUNNING, chat_id=chat_id, message_id=message_id)
        audit_id = await best_effort(self._out.repo.create(new), "новый аудит", None)
        job = Job(audit_id, user, chat_id, message_id, target, deadline)
        await self._finish(job, await self._outcome(job))

    async def _outcome(self, job: Job) -> AuditOutcome:
        """Отчёт из кэша места не ждёт; остальные ждут его внутри срока аудита, иначе — crowded (Л1)."""
        cached = self._auditor.cached(job.target)
        if cached is not None:
            return AuditOutcome(cached, from_cache=True)
        if not await self._take_place(job.deadline):
            return AuditOutcome(error_code=CROWDED)
        try:
            return await self._audit(job)
        finally:
            self._slots.release()

    async def _take_place(self, deadline: float) -> bool:
        try:
            await asyncio.wait_for(self._slots.acquire(), deadline - self._clock.monotonic())
        except TimeoutError:
            return False
        return True

    async def _audit(self, job: Job) -> AuditOutcome:
        """Срок — жёсткий: сколько бы ни осталось запросов, к сроку человек получает ответ (ТЗ, 5.3)."""
        meter = Meter(job.audit_id)
        try:
            return await asyncio.wait_for(self._auditor.run(job.target, job.deadline, meter),
                                          job.deadline - self._clock.monotonic())
        except TimeoutError:
            return AuditOutcome(error_code=SERVICE_DOWN, units=meter.units, reason=DEADLINE)
        except Exception:  # noqa: BLE001 — один аудит не должен ронять приём
            logger.exception("аудит {} упал", job.audit_id)
            return AuditOutcome(error_code=SERVICE_DOWN, units=meter.units, reason=BUG)

    async def _finish(self, job: Job, outcome: AuditOutcome) -> None:
        outcome, message, keyboard = self._final_message(job, outcome)
        await self._deliver(job, message, keyboard)
        self._limits.remember(job.user.user_id, outcome.charged, used_google=outcome.units > 0)
        if job.audit_id:
            await best_effort(self._out.repo.finish(job.audit_id, closing(job, outcome)), "итог аудита", None)
        await self._notify_owner(outcome)

    def _final_message(self, job: Job, outcome: AuditOutcome) -> tuple[AuditOutcome, dict, dict | None]:
        """Отчёт или отказ. Сборка отчёта упала — это наш сбой: service_down, попытка не списывается."""
        if outcome.facts is None:
            return outcome, self._failure(job, outcome), None
        try:
            message, keyboard = build_report(self._texts, job.user.lang, self._brand, outcome.facts,
                                             job.target.by_name)
        except Exception:  # noqa: BLE001 — неожиданное сочетание фактов не должно оставить «Смотрю канал…» навсегда
            logger.exception("отчёт аудита {} не собрался", job.audit_id)
            broken = AuditOutcome(error_code=SERVICE_DOWN, units=outcome.units, reason=BUG)
            return broken, self._failure(job, broken), None
        return outcome, message, keyboard

    def _failure(self, job: Job, outcome: AuditOutcome) -> dict:
        if outcome.error_code == QUOTA:
            return replies.quota(self._texts, job.user.lang, self._brand, hours_until_reset(self._clock.now()))
        return replies.failure(self._texts, job.user.lang, self._brand, outcome.error_code)

    async def _deliver(self, job: Job, message: dict, keyboard: dict | None) -> None:
        """Итог — до двух попыток с паузой; не прошли обе — один раз в журнал. Запись аудита закроется всё равно."""
        for attempt in range(1, DELIVERY_ATTEMPTS + 1):
            try:
                job.message_id = await edit_or_send(self._out.messenger, job.chat_id, job.message_id, message,
                                                    keyboard)
                return
            except DeliveryFailed as error:
                if attempt == DELIVERY_ATTEMPTS:
                    logger.warning("итог аудита {} не доставлен: {}", job.audit_id, error)
                else:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

    async def _notify_owner(self, outcome: AuditOutcome) -> None:
        """Паузы — раздел 8: ключ — раз в 6 часов, квота, потолок и ответ не той формы — раз в сутки."""
        if outcome.error_code == QUOTA:
            await self._notify_quota(outcome.reason)
        elif outcome.error_code == SERVICE_DOWN and outcome.reason == KEY:
            await self._out.notifier.notify(KEY, "notify_key", SIX_HOURS)
        elif outcome.error_code == SERVICE_DOWN and outcome.reason in SHAPE_REASONS:
            await self._out.notifier.notify(SHAPE, "notify_api_shape", DAY)

    async def _notify_quota(self, reason: str | None) -> None:
        if reason == CEILING:
            await self._out.notifier.notify(CEILING, "notify_units_ceiling", DAY, units=self._quota.units_today(),
                                            ceiling=self._quota.ceiling)
            return
        await self._out.notifier.notify(QUOTA, "notify_quota", DAY, hours=hours_until_reset(self._clock.now()))


class Intake:
    """Приём: разбор, отказы до сети, «занят», лимиты — затем аудит (ТЗ, разделы 4 и 9)."""

    def __init__(self, outputs: Outputs, users: Users, limits: Limits, auditor: Auditor, runner: AuditRunner,
                 clock: Clock):
        self._out = outputs
        self._texts, self._brand = outputs.texts, outputs.brand
        self._users = users
        self._limits = limits
        self._auditor = auditor
        self._runner = runner
        self._clock = clock
        self._busy: set[int] = set()

    async def handle_text(self, incoming: IncomingText) -> None:
        # Человек отмечен визитом раньше любой записи аудита — до разбора и до отказов (внешний ключ).
        user = await self._users.touch(incoming.user_id, incoming.language_code)
        parsed = parse_input(incoming.text, incoming.entity_urls)
        if isinstance(parsed, Rejection):
            await self._refuse(incoming.chat_id, user, None, parsed.code, *self._rejection(user, parsed))
            return
        if user.user_id in self._busy:
            await self._refuse(incoming.chat_id, user, parsed, BUSY, replies.busy(self._texts, user.lang, self._brand))
            return
        self._busy.add(user.user_id)  # сразу после проверки, без await между ними (В8)
        try:
            await self._audit_if_allowed(incoming.chat_id, user, parsed)
        finally:
            self._busy.discard(user.user_id)

    async def handle_not_text(self, user_id: int, chat_id: int, language_code: str | None) -> None:
        user = await self._users.touch(user_id, language_code)
        message = replies.failure(self._texts, user.lang, self._brand, NOT_TEXT)
        await self._refuse(chat_id, user, None, NOT_TEXT, message)

    def _rejection(self, user: User, rejection: Rejection) -> tuple[dict, dict | None]:
        if rejection.code == NOT_YOUTUBE:
            return replies.not_youtube(self._texts, user.lang, self._brand)
        return replies.failure(self._texts, user.lang, self._brand, rejection.code), None

    async def _audit_if_allowed(self, chat_id: int, user: User, target: Target) -> None:
        decision = await self._limits.decide(user.user_id, uses_google=self._auditor.cached(target) is None)
        if decision.allowed:
            await self._runner.run(chat_id, user, target)
            return
        await self._refuse(chat_id, user, target, decision.code, self._limit_message(user, decision))
        if decision.code == LIMIT_GLOBAL:
            await self._notify_global(decision)

    def _limit_message(self, user: User, decision: LimitDecision) -> dict:
        if decision.code == LIMIT_USER:
            hours = hours_until(decision.reopens_at, self._clock.now())
            return replies.limit_user(self._texts, user.lang, self._brand, self._limits.user_daily, hours)
        return replies.failure(self._texts, user.lang, self._brand, LIMIT_GLOBAL)

    async def _notify_global(self, decision: LimitDecision) -> None:
        audits = self._texts.count(OWNER_LANG, self._limits.global_daily, "audit")
        until = decision.reopens_at.astimezone(DISPLAY_TIMEZONE).strftime(OWNER_TIME_FORMAT)
        await self._out.notifier.notify(LIMIT_GLOBAL, "notify_global_limit", DAY, audits=audits, time=until)

    async def _refuse(self, chat_id: int, user: User, target: Target | None, code: str, message: dict,
                      keyboard: dict | None = None) -> None:
        try:
            await self._out.messenger.send(chat_id, message, keyboard)
        except DeliveryFailed as error:
            logger.warning("отказ не доставлен: {}", error)
        new = NewAudit(user.user_id, user.last_source, target.kind if target else None, FAILED, code)
        await best_effort(self._out.repo.create(new), "отказ", None)


@router.message(F.text.startswith(COMMAND_PREFIX))
async def on_unknown_command(message: Message, users: Users, messenger: Messenger, texts: Texts,
                             brand: Brand) -> None:
    user = await users.touch(message.from_user.id, message.from_user.language_code)
    await messenger.send(message.chat.id, replies.again(texts, user.lang, brand))


@router.message(F.text | F.caption)
async def on_text(message: Message, intake: Intake) -> None:
    await intake.handle_text(incoming_from(message))


@router.message()
async def on_other(message: Message, intake: Intake) -> None:
    await intake.handle_not_text(message.from_user.id, message.chat.id, message.from_user.language_code)


@router.callback_query(F.data == AGAIN_CALLBACK)
async def on_again(callback: CallbackQuery, users: Users, messenger: Messenger, texts: Texts, brand: Brand) -> None:
    # Устаревшее нажатие «Проверить другой канал» на старом отчёте не должно ронять обработчик.
    with contextlib.suppress(TelegramAPIError):
        await callback.answer()
    user = await users.touch(callback.from_user.id, callback.from_user.language_code)
    await messenger.send(callback.message.chat.id, replies.again(texts, user.lang, brand))
