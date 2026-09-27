import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetMyCommands
from aiogram.types import Chat, Message, Update
from loguru import logger

from bot import app
from bot.__main__ import EXIT_CONFIG
from bot.app import (ADMIN_COMMANDS, _error_recipient, _every, _shutdown, _throttle_notice_sender,
                     _upload_missing_banners, build_dispatcher, close_interrupted, closed_answer,
                     on_unexpected_error, setup_commands_best_effort, throttle_notice)
from bot.brand import BRAND
from bot.channel_audit.audits import RUNNING, AuditsRepo, NewAudit
from bot.channel_audit.banner import BannerSafeMessenger
from bot.channel_audit.handlers import Intake
from bot.channel_audit.kv import Kv
from bot.channel_audit.notifier import Notifier
from bot.core import rich
from bot.core.users import Users
from bot.locales import TEXTS
from tests.fakes import (ADMIN_ID, FAKE_NOW, FakeClock, FakeMessenger, fake_bot, fake_google_key, make_callback,
                         make_message, make_user)

ROOT = Path(__file__).resolve().parents[1]
STRANGER = 500
SECRET_MARKER = "секретные данные канала"


def test_missing_token_stops_start_without_showing_other_values():
    environ = {"PATH": "/usr/bin:/bin", "YOUTUBE_API_KEY": fake_google_key(), "ADMIN_ID": "1"}
    result = subprocess.run([sys.executable, "-B", "-m", "bot"], cwd=ROOT, env=environ, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == EXIT_CONFIG
    assert "bot_token" in result.stdout
    assert fake_google_key() not in result.stdout + result.stderr


async def test_only_private_chats_reach_the_bot(db, settings):
    """Единственный тест, который собирает диспетчер: роутеры модулей подключаются к родителю один раз за процесс."""
    clock, messenger = FakeClock(), FakeMessenger()
    dispatcher = build_dispatcher(settings, BRAND, Users(db, clock), AuditsRepo(db, clock), messenger, intake=None,
                                  quota=None, clock=clock)
    private = dispatcher.sub_routers[0]
    assert [router.name for router in private.sub_routers] == ["core_commands", "admin", "channel_audit"]
    assert [handler.callback for handler in dispatcher.errors.handlers] == [on_unexpected_error]
    in_group = Message(message_id=1, date=FAKE_NOW, chat=Chat(id=-100, type="supergroup"),
                       from_user=make_user(STRANGER), text="@bike_example")
    await dispatcher.feed_update(fake_bot(), Update(update_id=1, message=in_group))
    assert messenger.sent == []
    in_private = make_message("@bike_example", user_id=STRANGER)
    await dispatcher.feed_update(fake_bot(), Update(update_id=2, message=in_private))
    assert "Бот скоро откроется" in messenger.last()


async def test_build_wires_the_parts_without_network(settings, monkeypatch):
    """Сборка целиком, без сети: конструкторы сходятся; полос ещё нет — шапка строкой; потолок квоты — из настроек.
    Диспетчер подменён: настоящий собирает только тест выше."""
    wired = {}
    monkeypatch.setattr(app, "build_dispatcher", lambda *args: wired.setdefault("args", args))
    parts = await app.build(settings, FakeClock())
    try:
        _, brand, _, _, messenger, intake, quota, _ = wired["args"]
        assert brand.header("ru", "аудит-канала") == rich.header("аудит-канала")
        assert isinstance(messenger, BannerSafeMessenger) and isinstance(intake, Intake)
        assert quota.ceiling == settings.api_units_daily
    finally:
        await parts.http.close()
        await parts.engine.dispose()
        await parts.bot.session.close()


async def test_interrupted_audits_are_closed_on_start(db):
    clock = FakeClock()
    await Users(db, clock).touch(77, "ru", "channel")
    repo = AuditsRepo(db, clock)
    await repo.create(NewAudit(77, "channel", "handle", RUNNING, chat_id=77, message_id=9))
    messenger = FakeMessenger()
    await close_interrupted(repo, messenger, BRAND)
    assert messenger.edited[0][:2] == (77, 9)
    assert "Аудит прервался" in messenger.last()


def test_owner_menu_has_stats_channel_and_forget():
    assert ADMIN_COMMANDS == ("stats", "channel", "forget")


def test_throttle_notice_is_in_the_telegram_language():
    """Язык — из language_code Telegram: частое нажатие не стоит похода в базу за языком из /lang."""
    assert "Too fast" in throttle_notice(None)
    assert "Слишком часто" in throttle_notice("ru")


async def test_throttle_notice_is_an_article_and_survives_a_block():
    messenger = FakeMessenger()
    send_notice = _throttle_notice_sender(messenger, BRAND)
    await send_notice(42, "ru")
    assert messenger.last() == ">jw ~/аудит-канала_\nСлишком часто — подождите пару секунд."
    messenger.blocked.add(43)
    await send_notice(43, None)  # не должно бросить DeliveryFailed


async def test_closed_bot_answers_soon_to_strangers(db):
    messenger = FakeMessenger()
    answer = closed_answer(Users(db, FakeClock()), messenger, BRAND)
    await answer(make_message("@bike_example", user_id=STRANGER))
    assert "Бот скоро откроется" in messenger.last()
    bot = fake_bot()
    await answer(make_callback("again", user_id=STRANGER).as_(bot))
    assert [call.__api_method__ for call in bot.session.calls] == ["answerCallbackQuery"]


def test_error_recipient_reads_message_or_callback_query():
    message = make_message("boom", user_id=42, language_code="en")
    assert _error_recipient(Update(update_id=1, message=message)) == (42, "en")
    callback = make_callback("again", user_id=43, language_code="en")
    assert _error_recipient(Update(update_id=2, callback_query=callback)) == (43, "en")
    assert _error_recipient(Update(update_id=3)) is None


async def test_unhandled_handler_error_gets_a_short_reply_instead_of_silence():
    messenger = FakeMessenger()
    dispatcher = Dispatcher()
    dispatcher.workflow_data.update(messenger=messenger)
    dispatcher.errors.register(on_unexpected_error)

    @dispatcher.message()
    async def boom(message):
        raise RuntimeError("boom")

    await dispatcher.feed_update(fake_bot(), Update(update_id=1, message=make_message("@x_example", user_id=STRANGER)))
    assert "Что-то пошло не так" in messenger.last()


async def test_menu_setup_failure_is_logged_not_raised():
    """Меню — косметика: сбой Telegram здесь не должен ронять запуск бота."""
    error = TelegramBadRequest(method=SetMyCommands(commands=[]), message="boom")
    await setup_commands_best_effort(fake_bot({"setMyCommands": error}), admin_id=1)


async def test_background_loop_survives_a_failing_iteration_and_logs_only_the_type():
    """Общий цикл (ТЗ, 7.6): сбой итерации — не Telegram-исключение — не глушит повтор; в журнал — только тип."""
    calls: list[int] = []

    async def action() -> None:
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError(SECRET_MARKER)

    async def stop_after_second_iteration(seconds: float) -> None:
        if len(calls) >= 2:
            raise asyncio.CancelledError

    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        with pytest.raises(asyncio.CancelledError):
            await _every(0, action, "полосы", sleep=stop_after_second_iteration)
    finally:
        logger.remove(sink)
    assert calls == [0, 1]  # вторая итерация состоялась после сбоя первой
    log_text = "".join(lines)
    assert SECRET_MARKER not in log_text
    assert "RuntimeError" in log_text


class _StillMissingBanners:
    """Полоса не загрузилась и после попытки — как если бы Telegram не принял её или сеть подвела."""

    async def upload_missing(self, bot, admin_id: int) -> None:
        return None

    def missing(self) -> list[str]:
        return ["ru"]


async def test_owner_is_notified_once_a_day_when_a_banner_stays_missing(db):
    """Не только отказ Telegram по сохранённому file_id, но и сама неудачная загрузка — раз в сутки (ТЗ, раздел 8)."""
    messenger = FakeMessenger()
    notifier = Notifier(messenger, ADMIN_ID, FakeClock(), TEXTS, BRAND, Kv(db))
    await _upload_missing_banners(_StillMissingBanners(), fake_bot(), ADMIN_ID, notifier)
    assert "Полоса не загрузилась" in messenger.last()
    messenger.sent.clear()
    await _upload_missing_banners(_StillMissingBanners(), fake_bot(), ADMIN_ID, notifier)
    assert messenger.sent == []  # тот же день — повторного уведомления нет


class _NoopCloser:
    async def close(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


async def test_shutdown_logs_background_task_failures_by_type():
    """gather глушит исключение фоновой задачи (ТЗ, 7.6) — но не без следа: в журнал уходит только тип (Ю4)."""
    async def boom() -> None:
        raise RuntimeError(SECRET_MARKER)

    task = asyncio.create_task(boom(), name="полосы")
    await asyncio.sleep(0)  # дать задаче упасть до остановки
    parts = SimpleNamespace(http=_NoopCloser(), engine=_NoopCloser())
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        await _shutdown(parts, [task])
    finally:
        logger.remove(sink)
    log_text = "".join(lines)
    assert SECRET_MARKER not in log_text
    assert "RuntimeError" in log_text
