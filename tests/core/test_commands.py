import dataclasses

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.methods import AnswerCallbackQuery

from bot.brand import BRAND
from bot.core import rich
from bot.core.commands import (on_about, on_lang, on_lang_chosen, on_order, on_start, page_header, setup_commands,
                               simple_message)
from bot.core.messenger import EMPTY_KEYBOARD
from bot.core.users import Users
from bot.locales import TEXTS
from tests.fakes import ADMIN_ID, FakeClock, FakeMessenger, fake_bot, make_callback, make_message, rich_text

ADMIN_COMMANDS = ("stats", "channel", "forget")


def start(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="start", args=args)


def photo(lang: str, section: str) -> dict:
    return {"type": "photo", "photo": {"type": "photo", "media": f"banner-{lang}"}}


async def test_start_welcomes_owner_and_records_label(db, settings):
    messenger, users = FakeMessenger(), Users(db, FakeClock())
    await on_start(make_message("/start channel", user_id=ADMIN_ID), start("channel"), users=users,
                   messenger=messenger, texts=TEXTS, settings=settings, brand=BRAND)
    assert "Пришлите ссылку на YouTube-канал" in messenger.last()
    assert ">jw ~/аудит-канала_" in messenger.last()
    assert (await users.touch(ADMIN_ID, "ru")).last_source == "channel"


async def test_start_before_launch_answers_soon_to_others(db, settings):
    messenger = FakeMessenger()
    await on_start(make_message("/start fb", user_id=500), start("fb"), users=Users(db, FakeClock()),
                   messenger=messenger, texts=TEXTS, settings=settings, brand=BRAND)
    assert "Бот скоро откроется" in messenger.last()


async def test_lang_choice_and_callback_switch_language(db):
    messenger, users = FakeMessenger(), Users(db, FakeClock())
    await on_lang(make_message("/lang", user_id=500), users=users, messenger=messenger, texts=TEXTS, brand=BRAND)
    keyboard = messenger.sent[-1][2]
    assert [row[0]["text"] for row in keyboard["inline_keyboard"]] == ["Русский", "English"]
    callback = make_callback("lang:en", user_id=500).as_(fake_bot())
    await on_lang_chosen(callback, users=users, messenger=messenger, texts=TEXTS, brand=BRAND)
    assert "Done: I'll write in English." in messenger.last()
    assert (await users.touch(500, "ru")).lang == "en"
    assert messenger.edited[-1][3] == EMPTY_KEYBOARD


async def test_lang_chosen_survives_a_stale_callback(db):
    """Устаревшее нажатие («query is too old») не должно ронять выбор языка."""
    messenger, users = FakeMessenger(), Users(db, FakeClock())
    stale_answer = TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id="1"), message="query is too old")
    callback = make_callback("lang:en", user_id=500).as_(fake_bot({"answerCallbackQuery": stale_answer}))
    await on_lang_chosen(callback, users=users, messenger=messenger, texts=TEXTS, brand=BRAND)
    assert "Done: I'll write in English." in messenger.last()


async def test_about_has_buttons_and_footer(db):
    messenger = FakeMessenger()
    await on_about(make_message("/about"), users=Users(db, FakeClock()), messenger=messenger, texts=TEXTS, brand=BRAND)
    chat_id, message, keyboard = messenger.sent[-1]
    assert [row[0]["text"] for row in keyboard["inline_keyboard"]] == ["Сайт jw-dev.pro", "Канал"]
    assert rich_text(message).endswith("────\njw-dev.pro · @jw_dev_pro")


async def test_order_button_opens_dm_with_prefilled_text(db):
    messenger = FakeMessenger()
    await on_order(make_message("/order"), users=Users(db, FakeClock()), messenger=messenger, texts=TEXTS, brand=BRAND)
    button = messenger.sent[-1][2]["inline_keyboard"][0][0]
    assert button["url"].startswith("https://t.me/jw_dev_pro?text=")
    assert button["style"] == "primary"


async def test_setup_commands_touches_only_command_menu():
    bot = fake_bot()
    await setup_commands(bot, TEXTS, ADMIN_ID, ADMIN_COMMANDS)
    assert {call.__api_method__ for call in bot.session.calls} == {"setMyCommands"}


def test_without_header_builder_the_header_is_the_text_line():
    """Как у чекера: у бренда без поставщика шапка — моноширинная строка из локали."""
    assert page_header(TEXTS, "ru", BRAND) == rich.header("аудит-канала")
    assert page_header(TEXTS, "en") == rich.header("channel-audit")


def test_header_builder_replaces_the_text_line():
    brand = dataclasses.replace(BRAND, header=photo)
    message = simple_message(TEXTS, "en", "Hi", brand)
    assert rich_text(message) == "[фото banner-en]\nHi"


async def test_start_and_about_use_the_brand_header(db, settings):
    messenger, users = FakeMessenger(), Users(db, FakeClock())
    brand = dataclasses.replace(BRAND, header=photo)
    await on_start(make_message("/start", user_id=ADMIN_ID), start(None), users=users, messenger=messenger,
                   texts=TEXTS, settings=settings, brand=brand)
    assert messenger.last().startswith("[фото banner-ru]")
    await on_about(make_message("/about"), users=users, messenger=messenger, texts=TEXTS, brand=brand)
    assert messenger.last().startswith("[фото banner-ru]")
