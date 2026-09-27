import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import MessageEntity
from loguru import logger
from sqlalchemy import text

from bot.brand import BRAND
from bot.channel_audit import audit, audits, handlers, limits, replies
from bot.channel_audit import input as channel_input
from bot.channel_audit.audit import Auditor
from bot.channel_audit.audits import AuditsRepo
from bot.channel_audit.cache import DayCache
from bot.channel_audit.collect import Collector
from bot.channel_audit.handlers import (CROWDED, NOT_TEXT, AuditRunner, IncomingText, Intake, Outputs, entity_urls,
                                        on_again)
from bot.channel_audit.kv import Kv
from bot.channel_audit.limits import Limits
from bot.channel_audit.notifier import Notifier
from bot.channel_audit.quota import CEILING, QUOTA, QuotaGate
from bot.channel_audit.youtube import KEY, QuotaExhausted, ServiceDown
from bot.core.messenger import DeliveryFailed, MessageGone
from bot.core.users import Users
from bot.locales import TEXTS
from tests.builders import ScriptedClient, channel_item, days_ago, page, page_entry, video_item
from tests.fakes import ADMIN_ID, FakeClock, FakeMessenger, fake_bot, make_callback, rich_text

USER = 77
STATUS_ID = 101  # FakeMessenger нумерует с 101
OTHER_CHANNEL = "UCzyxwvutsrqZYXWVUTSRQ98"
RECENT_DAYS = range(1, 60, 6)  # 10 видео за 60 дней — видео выходят
UNEXPECTED_ERROR_MARKER = "неожиданный-сбой-текст-которого-в-журнал-попадать-не-должен"


@pytest.fixture(autouse=True)
def _no_real_retry_delay(monkeypatch):
    """Пауза перед второй попыткой доставки — настоящая в проде, в тестах ждать нечего."""
    monkeypatch.setattr(handlers, "RETRY_DELAY_SECONDS", 0)


class GatedClient(ScriptedClient):
    """Держит аудит, пока тест не откроет ворота."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def call(self, method, params, deadline, meter):
        await self.gate.wait()
        return await super().call(method, params, deadline, meter)


def working(client: ScriptedClient) -> ScriptedClient:
    client.channels["@bike_example"] = {"items": [channel_item()]}
    client.channels["@other_example"] = {"items": [channel_item(OTHER_CHANNEL, handle="@other-example")]}
    client.pages[None] = page([page_entry(f"v{day}", days_ago(day)) for day in RECENT_DAYS])
    for day in RECENT_DAYS:
        client.videos[f"v{day}"] = video_item(f"v{day}", days_ago(day))
    return client


def build_world(db, settings, client: ScriptedClient | None = None, messenger=None, slots=None,
                audit_seconds: float = handlers.AUDIT_SECONDS) -> SimpleNamespace:
    clock, messenger = FakeClock(), messenger or FakeMessenger()
    client = client or working(ScriptedClient())
    kv, repo = Kv(db), AuditsRepo(db, clock)
    auditor = Auditor(Collector(client, clock), DayCache(clock), DayCache(clock), clock)
    notifier = Notifier(messenger, settings.admin_id, clock, TEXTS, BRAND, kv)
    outputs = Outputs(messenger, notifier, repo, TEXTS, BRAND)
    limits_now = Limits(repo, clock, settings.user_daily_limit, settings.global_daily_limit, settings.admin_id)
    runner = AuditRunner(outputs, auditor, limits_now, QuotaGate(kv, clock, settings.api_units_daily),
                         slots or asyncio.Semaphore(settings.audit_workers), clock, audit_seconds)
    intake = Intake(outputs, Users(db, clock), limits_now, auditor, runner, clock)
    return SimpleNamespace(messenger=messenger, client=client, intake=intake, db=db)


@pytest.fixture
def world(db, settings):
    return build_world(db, settings)


def link(message_text: str, user_id: int = USER) -> IncomingText:
    return IncomingText(user_id, user_id, "ru", message_text, [])


async def rows(db, sql: str) -> list[tuple]:
    async with db.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(sql))]


def sent_to(world, chat_id: int) -> list[str]:
    return [rich_text(message) for chat, message, _ in world.messenger.sent if chat == chat_id]


async def wait_for_status(world) -> None:
    for _ in range(300):
        if world.messenger.sent:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("«Смотрю канал…» не отправлен")


async def test_link_gets_status_then_report_in_the_same_message(world):
    await world.intake.handle_text(link("youtube.com/@bike_example"))
    chat_id, status, keyboard = world.messenger.sent[0]
    assert (rich_text(status), keyboard) == (">jw ~/аудит-канала_\nСмотрю канал…", None)
    chat_id, message_id, report, keyboard = world.messenger.edited[-1]
    assert (chat_id, message_id) == (USER, STATUS_ID)
    assert "Байк-прокат Пример" in rich_text(report)
    assert keyboard["inline_keyboard"][0][0]["text"] == "Обсудить с разработчиком"
    assert await rows(world.db, "SELECT status, charged, from_cache, offered, handle, api_units FROM audits") == [
        ("done", 1, 0, 1, "@bike-example", 3)]


async def test_same_channel_again_comes_from_the_cache(world):
    await world.intake.handle_text(link("@bike_example"))
    await world.intake.handle_text(link("@Bike_Example", user_id=78))
    assert await rows(world.db, "SELECT from_cache, api_units, charged FROM audits ORDER BY id") == [
        (0, 3, 1), (1, 0, 1)]


async def test_not_a_link_is_explained_and_recorded_without_charge(world):
    await world.intake.handle_text(link("привет"))
    assert "Это не похоже на канал" in world.messenger.last()
    assert await rows(world.db, "SELECT status, error_code, charged, input_kind FROM audits") == [
        ("failed", "not_a_link", 0, None)]


async def test_not_youtube_offers_to_talk_to_the_developer(world):
    await world.intake.handle_text(link("https://instagram.com/bike_rental_example"))
    _, message, keyboard = world.messenger.sent[-1]
    assert "Это не YouTube" in rich_text(message)
    assert keyboard["inline_keyboard"][0][0]["text"] == "Обсудить с разработчиком"


async def test_not_found_is_charged(world):
    """Чужие @имена подряд не выжгут квоту даром: «не нашёл» списывает попытку (ТЗ, Л5)."""
    await world.intake.handle_text(link("@nobody_example"))
    assert "Не нашёл такой канал" in world.messenger.last()
    assert await rows(world.db, "SELECT status, error_code, charged, api_units FROM audits") == [
        ("failed", "not_found", 1, 1)]


async def test_channel_found_by_an_old_address_says_so(world):
    world.client.channels["@BikeName"] = {"items": [channel_item()]}
    await world.intake.handle_text(link("https://www.youtube.com/c/BikeName"))
    assert "Нашёл по имени — если это не тот канал" in world.messenger.last()


async def test_second_link_during_audit_is_refused(db, settings):
    world = build_world(db, settings, client=working(GatedClient()))
    first = asyncio.create_task(world.intake.handle_text(link("@bike_example")))
    await wait_for_status(world)
    await world.intake.handle_text(link("@other_example"))
    assert "Сначала закончу с этим каналом" in world.messenger.last()
    world.client.gate.set()
    await first
    assert [params.get("forHandle") for method, params in world.client.calls if method == "channels"] == [
        "@bike_example"]


async def test_deadline_expiry_is_logged_with_the_audit_id(db, settings):
    """DEADLINE переставал попадать в журнал вовсе (F8): владелец не видел, что аудиты упираются в срок."""
    world = build_world(db, settings, client=working(GatedClient()), audit_seconds=0.05)
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        await world.intake.handle_text(link("@bike_example"))
    finally:
        logger.remove(sink)
    audit_id = (await rows(world.db, "SELECT id FROM audits"))[0][0]
    log_text = "".join(lines)
    assert str(audit_id) in log_text
    assert "@bike_example" not in log_text and "bike_example" not in log_text


async def test_crowded_when_no_place_frees_up_in_time(db, settings):
    slots = asyncio.Semaphore(1)
    await slots.acquire()  # единственное место занято чужим аудитом
    world = build_world(db, settings, slots=slots, audit_seconds=0.05)
    await world.intake.handle_text(link("@bike_example"))
    assert "Сейчас много проверок" in world.messenger.last()
    assert world.client.calls == []
    assert await rows(world.db, "SELECT status, error_code, charged FROM audits") == [("failed", CROWDED, 0)]


async def test_report_is_sent_anew_when_status_message_is_gone(world):
    world.messenger.gone.add(STATUS_ID)
    await world.intake.handle_text(link("@bike_example"))
    _, report, keyboard = world.messenger.sent[-1]
    assert "Байк-прокат Пример" in rich_text(report)
    assert keyboard["inline_keyboard"][0][0]["text"] == "Обсудить с разработчиком"
    assert await rows(world.db, "SELECT message_id FROM audits") == [(STATUS_ID + 1,)]


async def test_blocked_user_still_closes_the_audit(db, settings):
    world = build_world(db, settings, client=working(GatedClient()))
    running = asyncio.create_task(world.intake.handle_text(link("@bike_example")))
    await wait_for_status(world)
    world.messenger.blocked.add(USER)
    world.client.gate.set()
    await running
    assert await rows(world.db, "SELECT status, charged FROM audits") == [("done", 1)]
    await world.intake.handle_text(link("@bike_example", user_id=78))
    assert "Байк-прокат Пример" in world.messenger.last()


async def test_quota_is_not_charged_and_the_owner_hears_once_a_day(db, settings):
    client = ScriptedClient()
    client.channels["@bike_example"] = QuotaExhausted(QUOTA)
    world = build_world(db, settings, client=client)
    await world.intake.handle_text(link("@bike_example"))
    await world.intake.handle_text(link("@bike_example", user_id=78))
    assert "Данные YouTube для меня закончились — откроются через 19 ч." in world.messenger.last()
    assert await rows(world.db, "SELECT error_code, charged FROM audits") == [("quota", 0), ("quota", 0)]
    owner = sent_to(world, ADMIN_ID)
    assert len(owner) == 1 and "через 19 ч" in owner[0]


async def test_own_ceiling_tells_the_owner_the_ceiling(db, settings):
    client = ScriptedClient()
    client.channels["@bike_example"] = QuotaExhausted(CEILING)
    world = build_world(db, settings, client=client)
    await world.intake.handle_text(link("@bike_example"))
    assert "это свой потолок 8000" in sent_to(world, ADMIN_ID)[0]


async def test_rejected_key_is_not_charged_and_the_owner_is_told(db, settings):
    client = ScriptedClient()
    client.channels["@bike_example"] = ServiceDown(KEY)
    world = build_world(db, settings, client=client)
    await world.intake.handle_text(link("@bike_example"))
    assert "Данные YouTube сейчас недоступны" in rich_text(world.messenger.edited[-1][2])  # «Смотрю канал…» исправлено
    assert await rows(world.db, "SELECT error_code, charged FROM audits") == [("service_down", 0)]
    assert "Google отклонил ключ YouTube" in sent_to(world, ADMIN_ID)[0]


async def test_user_limit_counts_reports_from_the_cache_too(world, settings):
    for _ in range(settings.user_daily_limit):
        await world.intake.handle_text(link("@bike_example"))
    await world.intake.handle_text(link("@bike_example"))
    assert world.messenger.last().endswith("Лимит — 10 аудитов в сутки. Следующий будет доступен через 24 ч.")


async def test_global_ceiling_skips_cached_channels_and_tells_the_owner(db, settings):
    world = build_world(db, settings.model_copy(update={"global_daily_limit": 1}))
    await world.intake.handle_text(link("@bike_example"))
    await world.intake.handle_text(link("@bike_example", user_id=78))  # из кэша — в потолок не входит
    assert "Байк-прокат Пример" in world.messenger.last()
    await world.intake.handle_text(link("@other_example", user_id=79))
    assert "Сегодня аудитов было слишком много" in sent_to(world, 79)[-1]
    assert sent_to(world, ADMIN_ID)[0].endswith(
        "Сработал общий потолок: 1 аудит за сутки. Новые люди получают «попробуйте завтра» до 26.09 19:00.")


async def test_not_text_is_recorded_for_a_new_person(world):
    """touch() отмечает человека раньше записи отказа — иначе внешний ключ уронил бы вставку."""
    await world.intake.handle_not_text(555, 555, "ru")
    assert "Пришлите ссылку текстом" in world.messenger.last()
    assert await rows(world.db, "SELECT status, error_code FROM audits") == [("failed", NOT_TEXT)]


async def test_broken_report_builder_does_not_leave_the_status_forever(world, monkeypatch):
    """Сборка отчёта упала — наш сбой: человеку «данные недоступны», попытка не списывается."""
    def boom(*args, **kwargs):
        raise RuntimeError("отчёт не собрался")

    monkeypatch.setattr(handlers, "build_report", boom)
    await world.intake.handle_text(link("@bike_example"))
    assert "Данные YouTube сейчас недоступны" in world.messenger.last()
    assert await rows(world.db, "SELECT status, error_code, charged FROM audits") == [("failed", "service_down", 0)]


async def test_final_message_delivery_recovers_after_one_retry(db, settings):
    inner = FakeMessenger()

    class FlakyOnce:
        def __init__(self) -> None:
            self.broken_edits_left = 1

        async def send(self, chat_id, rich_message, reply_markup=None):
            return await inner.send(chat_id, rich_message, reply_markup)

        async def edit(self, chat_id, message_id, rich_message, reply_markup=None):
            if self.broken_edits_left:
                self.broken_edits_left -= 1
                raise DeliveryFailed("временный сбой")
            await inner.edit(chat_id, message_id, rich_message, reply_markup)

    world = build_world(db, settings, messenger=FlakyOnce())
    await world.intake.handle_text(link("@bike_example"))
    assert "Байк-прокат Пример" in rich_text(inner.edited[-1][2])


class GoneThenBrokenResend:
    """Правка сообщения не находит его (message gone), а повторная отправка человеку падает с неожиданной
    ошибкой — не с DeliveryFailed. Первая отправка «Смотрю канал…» и отправка владельцу идут как обычно."""

    def __init__(self, inner: FakeMessenger, chat_id: int, marker: str) -> None:
        self._inner = inner
        self._chat_id = chat_id
        self._marker = marker
        self._first_send_done = False

    async def send(self, chat_id, rich_message, reply_markup=None):
        if chat_id == self._chat_id and self._first_send_done:
            raise RuntimeError(self._marker)
        self._first_send_done = self._first_send_done or chat_id == self._chat_id
        return await self._inner.send(chat_id, rich_message, reply_markup)

    async def edit(self, chat_id, message_id, rich_message, reply_markup=None):
        raise MessageGone("message to edit not found")


async def test_report_delivery_survives_an_unexpected_error_and_still_tells_the_owner(db, settings):
    """Правка падает с message gone, а повторная отправка — с неожиданной ошибкой (не DeliveryFailed):
    учёт всё равно закрывается, владелец всё равно узнаёт, а в журнал уходит только тип ошибки (Ю4)."""
    client = ScriptedClient()
    client.channels["@bike_example"] = ServiceDown(KEY)
    inner = FakeMessenger()
    world = build_world(db, settings, client=client,
                        messenger=GoneThenBrokenResend(inner, USER, UNEXPECTED_ERROR_MARKER))
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        await world.intake.handle_text(link("@bike_example"))
    finally:
        logger.remove(sink)
    log_text = "".join(lines)
    assert UNEXPECTED_ERROR_MARKER not in log_text
    assert "RuntimeError" in log_text
    assert await rows(world.db, "SELECT status, error_code, charged FROM audits") == [("failed", "service_down", 0)]
    admin_messages = [rich_text(message) for chat, message, _ in inner.sent if chat == ADMIN_ID]
    assert admin_messages and "Google отклонил ключ YouTube" in admin_messages[0]
    assert USER not in world.intake._busy  # занятость снята несмотря на неожиданный сбой доставки


async def test_refusal_delivery_survives_an_unexpected_error(db, settings):
    """Отправка отказа падает с неожиданной ошибкой: запись всё равно пишется, в журнал — только тип ошибки."""
    class BrokenSend:
        async def send(self, chat_id, rich_message, reply_markup=None):
            raise RuntimeError(UNEXPECTED_ERROR_MARKER)

        async def edit(self, chat_id, message_id, rich_message, reply_markup=None):
            raise RuntimeError(UNEXPECTED_ERROR_MARKER)

    world = build_world(db, settings, messenger=BrokenSend())
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        await world.intake.handle_text(link("привет"))
    finally:
        logger.remove(sink)
    log_text = "".join(lines)
    assert UNEXPECTED_ERROR_MARKER not in log_text
    assert "RuntimeError" in log_text
    assert await rows(world.db, "SELECT status, error_code, charged FROM audits") == [
        ("failed", "not_a_link", 0)]


def test_entity_urls_take_links_and_text_links():
    message_text = "мой канал youtu.be/Ab3dE5gH1jK и вот ещё"
    entities = [MessageEntity(type="url", offset=10, length=20),
                MessageEntity(type="text_link", offset=33, length=3, url="https://www.youtube.com/@bike_example")]
    assert entity_urls(message_text, entities) == ["youtu.be/Ab3dE5gH1jK", "https://www.youtube.com/@bike_example"]


async def test_on_again_survives_a_stale_callback(db):
    users, messenger = Users(db, FakeClock()), FakeMessenger()
    stale_answer = TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id="1"), message="query is too old")
    callback = make_callback("again", user_id=USER).as_(fake_bot({"answerCallbackQuery": stale_answer}))
    await on_again(callback, users=users, messenger=messenger, texts=TEXTS, brand=BRAND)
    assert "Пришлите ссылку на YouTube-канал" in messenger.last()


# Коды отказов — из констант самих модулей, не переписаны строками заново.
PRODUCIBLE_FAILURE_CODES = sorted({channel_input.NOT_A_LINK, channel_input.PLAYLIST, NOT_TEXT, CROWDED,
                                   audit.NOT_FOUND, audit.LEGACY_NOT_FOUND, audit.VIDEO_NOT_FOUND,
                                   audit.SERVICE_DOWN, limits.LIMIT_GLOBAL, audits.INTERRUPTED})


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("code", PRODUCIBLE_FAILURE_CODES)
def test_every_producible_failure_code_has_a_reply(code, lang):
    # Без этой строки тест не мог бы упасть: failure() тихо подменяет неизвестный код на service_down.
    assert code in replies.FAILURE_CODES
    assert "{" not in rich_text(replies.failure(TEXTS, lang, BRAND, code))
