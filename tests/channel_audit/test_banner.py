import struct
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto
from aiogram.types import Chat, Message, PhotoSize

from bot.channel_audit.banner import BANNER_FILES, BannerSafeMessenger, Banners, photo_block
from bot.channel_audit.kv import Kv
from bot.core import rich
from bot.core.messenger import DeliveryFailed, MessageGone, edit_or_send
from bot.locales import TEXTS
from tests.fakes import FAKE_NOW, FakeMessenger, fake_bot

ASSETS = Path(__file__).resolve().parents[2] / "bot" / "assets"
PNG_SIZE = struct.Struct(">II")
IHDR_SIZE_AT = 16  # ширина и высота в заголовке PNG
USER = 77
STATUS_ID = 101


@pytest.fixture
def assets(tmp_path) -> Path:
    for lang, name in BANNER_FILES.items():
        (tmp_path / name).write_bytes(f"картинка {lang}".encode())
    return tmp_path


@pytest.fixture
async def banners(db, assets) -> Banners:
    loaded = Banners(Kv(db), TEXTS, assets)
    await loaded.load()
    return loaded


def sent_photo(file_id: str) -> Message:
    sizes = [PhotoSize(file_id=f"{file_id}-small", file_unique_id="s", width=320, height=80),
             PhotoSize(file_id=file_id, file_unique_id="b", width=1600, height=400)]
    return Message(message_id=900, date=FAKE_NOW, chat=Chat(id=1, type="private"), photo=sizes)


def article(banners: Banners, text: str) -> dict:
    return rich.message([banners.header("ru", "аудит-канала"), rich.paragraph(text)])


class RejectingMessenger(FakeMessenger):
    """Telegram не принимает статью с полосой: отправка — DeliveryFailed, правка — MessageGone (ядро, messenger.py)."""

    async def send(self, chat_id, rich_message, reply_markup=None):
        if rich_message["blocks"][0]["type"] == "photo":
            raise DeliveryFailed("Bad Request: wrong file identifier")
        return await super().send(chat_id, rich_message, reply_markup)

    async def edit(self, chat_id, message_id, rich_message, reply_markup=None):
        if rich_message["blocks"][0]["type"] == "photo":
            raise MessageGone("Bad Request: wrong file identifier")
        await super().edit(chat_id, message_id, rich_message, reply_markup)


def test_banner_pictures_are_1600_by_400():
    for name in BANNER_FILES.values():
        assert PNG_SIZE.unpack_from((ASSETS / name).read_bytes(), IHDR_SIZE_AT) == (1600, 400)


async def test_until_uploaded_the_header_is_the_text_line(banners):
    assert banners.header("ru", "аудит-канала") == rich.header("аудит-канала")
    assert banners.missing() == ["ru", "en"]


async def test_upload_is_silent_keeps_the_largest_size_and_deletes_the_message(banners, db, assets):
    bot = fake_bot({"sendPhoto": sent_photo("big-id")})
    await banners.upload_missing(bot, chat_id=1)
    assert [call.__api_method__ for call in bot.session.calls] == ["sendPhoto", "deleteMessage"] * 2
    assert bot.session.calls[0].disable_notification is True
    assert banners.header("en", "channel-audit") == photo_block("big-id")
    restarted = Banners(Kv(db), TEXTS, assets)
    await restarted.load()
    assert restarted.missing() == []


async def test_new_picture_means_a_new_upload(banners, db, assets):
    await banners.remember("ru", "old-id")
    (assets / BANNER_FILES["ru"]).write_bytes(b"new picture")
    changed = Banners(Kv(db), TEXTS, assets)
    await changed.load()
    assert changed.missing() == ["ru", "en"]


async def test_failed_upload_leaves_the_text_line(banners):
    error = TelegramBadRequest(method=SendPhoto(chat_id=1, photo="x"), message="boom")
    await banners.upload_missing(fake_bot({"sendPhoto": error}), chat_id=1)
    assert banners.missing() == ["ru", "en"]


async def test_rejected_banner_falls_back_to_text_header(banners):
    await banners.remember("ru", "stale-id")
    inner, notices = RejectingMessenger(), []
    messenger = BannerSafeMessenger(inner, banners)

    async def notify_owner() -> None:
        notices.append("banner")

    messenger.on_rejected = notify_owner
    await messenger.send(USER, article(banners, "Смотрю канал…"))
    assert inner.last() == ">jw ~/аудит-канала_\nСмотрю канал…"
    assert banners.missing() == ["ru", "en"]
    assert notices == ["banner"]


async def test_rejected_banner_in_an_edit_falls_back_too(banners):
    await banners.remember("ru", "stale-id")
    inner = RejectingMessenger()
    await BannerSafeMessenger(inner, banners).edit(USER, STATUS_ID, article(banners, "Отчёт"))
    assert inner.edited[-1][1] == STATUS_ID
    assert inner.last() == ">jw ~/аудит-канала_\nОтчёт"


async def test_blocked_chat_does_not_forget_the_banner(banners):
    """Не прошёл и повтор со строкой — полоса не виновата: бот заблокирован."""
    await banners.remember("ru", "good-id")
    inner = FakeMessenger()
    inner.blocked.add(USER)
    with pytest.raises(DeliveryFailed):
        await BannerSafeMessenger(inner, banners).send(USER, article(banners, "Отчёт"))
    assert banners.missing() == ["en"]


async def test_deleted_status_gets_a_new_message_with_the_banner(banners):
    """Сообщение удалено: правка не проходит ни с полосой, ни со строкой — отчёт уходит новым, полоса остаётся."""
    await banners.remember("ru", "good-id")
    inner = FakeMessenger()
    inner.gone.add(STATUS_ID)
    await edit_or_send(BannerSafeMessenger(inner, banners), USER, STATUS_ID, article(banners, "Отчёт"))
    assert inner.last() == "[фото good-id]\nОтчёт"
    assert banners.missing() == ["en"]


async def test_message_without_banner_is_passed_through(banners):
    inner = FakeMessenger()
    inner.blocked.add(USER)
    with pytest.raises(DeliveryFailed):
        await BannerSafeMessenger(inner, banners).send(USER, rich.message([rich.header("x"), rich.paragraph("y")]))
