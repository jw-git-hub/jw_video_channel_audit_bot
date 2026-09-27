"""Сборка и запуск бота (ТЗ, разделы 9, 12, 13): база, aiogram, аудит, фоновые задачи, сторож зависания.

Как у чекера, но без очереди и защиты сети: вместо них — ограничитель на AUDIT_WORKERS аудитов, полоса с откатом
на строку, обслуживание базы (уборка данных YouTube перед суточной копией) и загрузка полос фоном.
"""
import asyncio
import contextlib
import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ErrorEvent, TelegramObject, Update
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.brand import BRAND
from bot.channel_audit import admin, handlers, replies
from bot.channel_audit.audit import Auditor
from bot.channel_audit.audits import INTERRUPTED, AuditsRepo
from bot.channel_audit.banner import BannerSafeMessenger, Banners
from bot.channel_audit.cache import DayCache
from bot.channel_audit.collect import Collector
from bot.channel_audit.handlers import AuditRunner, Intake, Outputs
from bot.channel_audit.kv import Kv
from bot.channel_audit.limits import Limits
from bot.channel_audit.notifier import DAY, Notifier
from bot.channel_audit.quota import QuotaGate
from bot.channel_audit.youtube import YouTubeClient
from bot.core import commands
from bot.core.access import OpenGate
from bot.core.clock import Clock, SystemClock
from bot.core.commands import Brand
from bot.core.db import BACKUP_DIR_NAME, create_engine, migrate
from bot.core.i18n import detect_lang
from bot.core.messenger import AiogramMessenger, DeliveryFailed, Messenger, edit_or_send
from bot.core.stats import best_effort
from bot.core.throttle import ThrottleMiddleware
from bot.core.users import Users
from bot.core.watchdog import EVENT_LOOP, POLLING, Heartbeat, PollingPulse, loop_pulse, start_watchdog
from bot.locales import TEXTS
from bot.maintenance import daily_maintenance
from bot.schema import MIGRATIONS
from bot.settings import Settings

ALLOWED_UPDATES = ["message", "callback_query"]
MESSAGE_INTERVAL_SECONDS = 2.0
BUTTON_INTERVAL_SECONDS = 0.7
ADMIN_COMMANDS = ("stats", "channel", "forget")
MAINTENANCE_EVERY_SECONDS = 6 * 3600
BANNER_RETRY_SECONDS = 3600  # недостающая полоса — не чаще раза в час (ТЗ, 7.6)
STAMP_FORMAT = "%Y%m%d-%H%M%S"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


@dataclass
class Parts:
    bot: Bot
    dispatcher: Dispatcher
    engine: AsyncEngine
    http: aiohttp.ClientSession
    repo: AuditsRepo
    messenger: Messenger
    brand: Brand
    banners: Banners
    heartbeat: Heartbeat
    notifier: Notifier


async def build(settings: Settings, clock: Clock) -> Parts:
    engine = create_engine(settings.data_dir)
    await migrate(engine, MIGRATIONS, settings.data_dir / BACKUP_DIR_NAME, clock.now().strftime(STAMP_FORMAT))
    heartbeat, kv = Heartbeat(), Kv(engine)
    bot = Bot(token=settings.bot_token.get_secret_value())
    bot.session.middleware(PollingPulse(heartbeat))
    banners = Banners(kv, TEXTS, ASSETS_DIR)
    await banners.load()
    brand = dataclasses.replace(BRAND, header=banners.header)  # шапка — полоса, пока её нет — строка (ТЗ, 7.6)
    messenger = BannerSafeMessenger(AiogramMessenger(bot), banners)
    notifier = Notifier(messenger, settings.admin_id, clock, TEXTS, brand, kv)
    messenger.on_rejected = lambda: notifier.notify("banner", "notify_banner", DAY)
    http = aiohttp.ClientSession(trust_env=False)  # прокси из окружения не берём (ТЗ, С2)
    users, repo, quota = Users(engine, clock), AuditsRepo(engine, clock), QuotaGate(kv, clock, settings.api_units_daily)
    await quota.load()
    intake = _auditing(settings, clock, Outputs(messenger, notifier, repo, TEXTS, brand), users, quota, http)
    dispatcher = build_dispatcher(settings, brand, users, repo, messenger, intake, quota, clock)
    return Parts(bot, dispatcher, engine, http, repo, messenger, brand, banners, heartbeat, notifier)


def _auditing(settings: Settings, clock: Clock, outputs: Outputs, users: Users, quota: QuotaGate,
              http: aiohttp.ClientSession) -> Intake:
    client = YouTubeClient(http, settings.youtube_api_key.get_secret_value(), clock, quota)
    auditor = Auditor(Collector(client, clock), DayCache(clock), DayCache(clock), clock)
    limits = Limits(outputs.repo, clock, settings.user_daily_limit, settings.global_daily_limit, settings.admin_id)
    runner = AuditRunner(outputs, auditor, limits, quota, asyncio.Semaphore(settings.audit_workers), clock)
    return Intake(outputs, users, limits, auditor, runner, clock)


def build_dispatcher(settings: Settings, brand: Brand, users: Users, repo: AuditsRepo, messenger: Messenger,
                     intake: Intake | None, quota: QuotaGate | None, clock: Clock) -> Dispatcher:
    """Данные диспетчера — зависимости обработчиков по имени параметра."""
    dispatcher = Dispatcher()
    dispatcher.workflow_data.update(settings=settings, texts=TEXTS, brand=brand, users=users, repo=repo,
                                    messenger=messenger, intake=intake, quota=quota, clock=clock)
    dispatcher.message.filter(F.chat.type == ChatType.PRIVATE)  # только личка (ТЗ, Р6)
    dispatcher.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    dispatcher.include_router(private_chats(settings, brand, users, messenger))
    dispatcher.errors.register(on_unexpected_error)  # последний рубеж
    return dispatcher


async def on_unexpected_error(event: ErrorEvent, messenger: Messenger, brand: Brand = BRAND) -> None:
    """Необработанная ошибка обработчика не обрывается без ответа: короткий отказ вместо тишины, подробности —
    в журнал. Сбой самой отправки подавляется: если сообщение не доставить, помочь тут уже нечем."""
    logger.exception("необработанная ошибка обработчика: {}", event.exception)
    recipient = _error_recipient(event.update)
    if recipient is None:
        return
    chat_id, language_code = recipient
    lang = detect_lang(language_code)
    with contextlib.suppress(TelegramAPIError, DeliveryFailed):
        await messenger.send(chat_id, commands.simple_message(TEXTS, lang, TEXTS.get(lang, "unexpected_error"), brand))


def _error_recipient(update: Update) -> tuple[int, str | None] | None:
    """Чат и язык человека — message и callback_query единственные обновления, что доходят до бота."""
    if update.message:
        return update.message.chat.id, update.message.from_user.language_code
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat.id, update.callback_query.from_user.language_code
    return None


def private_chats(settings: Settings, brand: Brand, users: Users, messenger: Messenger) -> Router:
    """Частота и режим до запуска — внешние слои этого роутера: на диспетчере они сработали бы раньше фильтра лички."""
    router = Router(name="private_chats")
    gate = OpenGate(settings, closed_answer(users, messenger, brand))
    send_notice = _throttle_notice_sender(messenger, brand)
    for observer, interval in ((router.message, MESSAGE_INTERVAL_SECONDS),
                               (router.callback_query, BUTTON_INTERVAL_SECONDS)):
        observer.outer_middleware(ThrottleMiddleware(interval, throttle_notice, send_notice))
        observer.outer_middleware(gate)
    router.include_routers(commands.router, admin.router, handlers.router)
    return router


def throttle_notice(language_code: str | None) -> str:
    # Язык, выбранный через /lang, здесь недоступен без похода в базу на каждое частое нажатие — осознанно берём
    # language_code Telegram, как у чекера.
    return TEXTS.get(detect_lang(language_code), "throttled")


def _throttle_notice_sender(messenger: Messenger, brand: Brand) -> Callable[[int, str | None], Awaitable[None]]:
    """send_notice для ThrottleMiddleware: статья с шапкой, доставка — по возможности."""
    async def send(chat_id: int, language_code: str | None) -> None:
        lang = detect_lang(language_code)
        message = commands.simple_message(TEXTS, lang, throttle_notice(language_code), brand)
        with contextlib.suppress(DeliveryFailed):
            await messenger.send(chat_id, message)
    return send


def closed_answer(users: Users, messenger: Messenger, brand: Brand) -> Callable[[TelegramObject], Awaitable[None]]:
    """Ответ до запуска (ТЗ, раздел 3): человека записываем и говорим, что бот скоро откроется."""
    async def answer(event: TelegramObject) -> None:
        user = await users.touch(event.from_user.id, event.from_user.language_code)
        text = TEXTS.get(user.lang, "not_open_yet")
        with contextlib.suppress(TelegramAPIError, DeliveryFailed):
            if isinstance(event, CallbackQuery):
                await event.answer(text)
            else:
                await messenger.send(event.chat.id, commands.simple_message(TEXTS, user.lang, text, brand))
    return answer


async def close_interrupted(repo: AuditsRepo, messenger: Messenger, brand: Brand) -> None:
    """После перезапуска прерванные аудиты не повторяются: один уронил бота — повтор уронит снова (ТЗ, Л6)."""
    for item in await best_effort(repo.interrupt_unfinished(), "незаконченные аудиты", []):
        message = replies.failure(TEXTS, item.lang, brand, INTERRUPTED)
        with contextlib.suppress(DeliveryFailed):
            await edit_or_send(messenger, item.chat_id, item.message_id, message)


async def setup_commands_best_effort(bot: Bot, admin_id: int) -> None:
    """Меню команд — косметика: сбой Telegram здесь не повод для петли перезапусков."""
    try:
        await commands.setup_commands(bot, TEXTS, admin_id, ADMIN_COMMANDS)
    except TelegramAPIError as error:
        logger.warning("не удалось настроить меню команд: {}", error)


async def maintenance_loop(engine: AsyncEngine, backup_dir: Path, clock: Clock) -> None:
    """Уборка данных YouTube и копия базы — при запуске и раз в 6 часов; копия за день — одна (ТЗ, раздел 12)."""
    await _every(MAINTENANCE_EVERY_SECONDS, lambda: daily_maintenance(engine, backup_dir, clock.now()),
                "обслуживание базы")


async def banner_uploads(banners: Banners, bot: Bot, admin_id: int, notifier: Notifier) -> None:
    """Полосы — фоном при запуске; недостающие — раз в час (ТЗ, 7.6). Не загрузилась — владельцу раз в сутки,
    той же паузой notify_banner, что и отказ Telegram по сохранённому file_id (ТЗ, раздел 8)."""
    await _every(BANNER_RETRY_SECONDS, lambda: _upload_missing_banners(banners, bot, admin_id, notifier), "полосы")


async def _upload_missing_banners(banners: Banners, bot: Bot, admin_id: int, notifier: Notifier) -> None:
    await banners.upload_missing(bot, admin_id)
    if banners.missing():
        await notifier.notify("banner", "notify_banner", DAY)


async def _every(seconds: float, action: Callable[[], Awaitable[None]], what: str,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Общий цикл фоновой задачи: сбой одной итерации не должен остановить повтор — кроме отмены при остановке."""
    while True:
        await _run_once(action, what)
        await sleep(seconds)


async def _run_once(action: Callable[[], Awaitable[None]], what: str) -> None:
    try:
        await action()
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 — сбой одной итерации не должен ронять фоновый цикл
        logger.warning("{}: сбой — {}", what, type(error).__name__)


async def run(settings: Settings) -> None:
    clock = SystemClock()
    parts = await build(settings, clock)
    await close_interrupted(parts.repo, parts.messenger, parts.brand)
    await setup_commands_best_effort(parts.bot, settings.admin_id)
    await parts.bot.delete_webhook(drop_pending_updates=False)  # присланное, пока бот лежал, — ответить (ТЗ, Л7)
    background = _start_background(parts, settings, clock)
    try:
        await parts.dispatcher.start_polling(parts.bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await _shutdown(parts, background)


def _start_background(parts: Parts, settings: Settings, clock: Clock) -> list[asyncio.Task]:
    parts.heartbeat.beat(EVENT_LOOP)
    parts.heartbeat.beat(POLLING)
    start_watchdog(parts.heartbeat)
    backup_dir = settings.data_dir / BACKUP_DIR_NAME
    return [asyncio.create_task(loop_pulse(parts.heartbeat), name="пульс"),
            asyncio.create_task(maintenance_loop(parts.engine, backup_dir, clock), name="обслуживание базы"),
            asyncio.create_task(banner_uploads(parts.banners, parts.bot, settings.admin_id, parts.notifier),
                                name="полосы")]


async def _shutdown(parts: Parts, background: list[asyncio.Task]) -> None:
    for task in background:
        task.cancel()
    results = await asyncio.gather(*background, return_exceptions=True)
    _log_background_failures(background, results)
    await parts.http.close()
    await parts.engine.dispose()


def _log_background_failures(tasks: list[asyncio.Task], results: list[object]) -> None:
    """CancelledError — обычный итог остановки, не сбой; остальное — в журнал только по типу (Ю4)."""
    for task, result in zip(tasks, results):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            logger.warning("{}: не завершилась чисто — {}", task.get_name(), type(result).__name__)
