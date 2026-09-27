"""Полоса-шапка (ТЗ, 7.6): картинка по file_id, пока его нет — строка; отказ Telegram — строка, file_id забыт.

Полоса загружается фоном: sendPhoto владельцу без звука, file_id — в kv с хэшем файла, сообщение сразу удаляется.
Поменялась картинка — хэш другой, загрузится заново. Сообщения загрузку не ждут. Откат делает обёртка мессенджера
здесь же: ядро берёт мессенджер из данных диспетчера, поэтому правка ядра для него не нужна (ТЗ, 13).
"""
import contextlib
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from loguru import logger

from bot.channel_audit.kv import Kv
from bot.core import rich
from bot.core.i18n import Lang, Texts
from bot.core.messenger import DeliveryFailed, MessageGone, Messenger
from bot.core.stats import best_effort

BANNER_FILES: dict[Lang, str] = {"ru": "banner_ru.png", "en": "banner_en.png"}
KEY_TEMPLATE = "banner:{lang}:{digest}"
DIGEST_CHARS = 16
PHOTO = "photo"
WHAT = "file_id полосы"


def photo_block(file_id: str) -> dict[str, Any]:
    return {"type": PHOTO, "photo": {"type": PHOTO, "media": file_id}}


class Banners:
    def __init__(self, kv: Kv, texts: Texts, assets_dir: Path):
        self._kv = kv
        self._texts = texts
        self._paths = {lang: assets_dir / name for lang, name in BANNER_FILES.items()}
        self._keys = {lang: _key(lang, path) for lang, path in self._paths.items()}
        self._file_ids: dict[Lang, str] = {}

    async def load(self) -> None:
        """file_id полос из kv — только загруженные для нынешних картинок."""
        for lang, key in self._keys.items():
            file_id = await best_effort(self._kv.get(key), WHAT, None)
            if file_id:
                self._file_ids[lang] = file_id

    def missing(self) -> list[Lang]:
        return [lang for lang in self._keys if lang not in self._file_ids]

    def header(self, lang: Lang, section: str) -> dict[str, Any]:
        """Поставщик шапки для Brand.header (правка ядра 1): полоса, а пока её нет — строка."""
        file_id = self._file_ids.get(lang)
        return photo_block(file_id) if file_id else rich.header(section)

    def text_header(self, lang: Lang) -> dict[str, Any]:
        return rich.header(self._texts.get(lang, "header_section"))

    def lang_of(self, block: dict[str, Any]) -> Lang | None:
        """Чья полоса в блоке; None — блок не полоса этого бота."""
        if block.get("type") != PHOTO:
            return None
        media = block.get(PHOTO, {}).get("media")
        return next((lang for lang, file_id in self._file_ids.items() if file_id == media), None)

    async def remember(self, lang: Lang, file_id: str) -> None:
        self._file_ids[lang] = file_id
        await best_effort(self._kv.set(self._keys[lang], file_id), WHAT, None)

    async def forget(self, lang: Lang) -> None:
        self._file_ids.pop(lang, None)
        await best_effort(self._kv.delete(self._keys[lang]), WHAT, None)

    async def upload_missing(self, bot: Bot, chat_id: int) -> None:
        for lang in self.missing():
            await self._upload(bot, chat_id, lang)

    async def _upload(self, bot: Bot, chat_id: int, lang: Lang) -> None:
        try:
            sent = await bot.send_photo(chat_id, FSInputFile(self._paths[lang]), disable_notification=True)
        except TelegramAPIError as error:
            logger.warning("полоса {} не загрузилась, пока строка: {}", lang, error)
            return
        await self.remember(lang, sent.photo[-1].file_id)  # самый большой размер
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(chat_id, sent.message_id)


def _key(lang: Lang, path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_CHARS]
    return KEY_TEMPLATE.format(lang=lang, digest=digest)


class BannerSafeMessenger:
    """Мессенджер с откатом (ТЗ, 7.6). Telegram не принял статью с полосой — та же статья со строкой вместо полосы,
    file_id забывается, владельцу — уведомление. Не прошёл и повтор (бот заблокирован, сообщение удалено) —
    полоса не виновата: ошибка идёт дальше, file_id остаётся."""

    def __init__(self, inner: Messenger, banners: Banners):
        self._inner = inner
        self._banners = banners
        self.on_rejected: Callable[[], Awaitable[object]] | None = None

    async def send(self, chat_id: int, rich_message: dict[str, Any],
                   reply_markup: dict[str, Any] | None = None) -> int:
        try:
            return await self._inner.send(chat_id, rich_message, reply_markup)
        except DeliveryFailed:
            lang = self._banner_lang(rich_message)
            if lang is None:
                raise
            message_id = await self._inner.send(chat_id, self._with_text(rich_message, lang), reply_markup)
            await self._rejected(lang)
            return message_id

    async def edit(self, chat_id: int, message_id: int, rich_message: dict[str, Any],
                   reply_markup: dict[str, Any] | None = None) -> None:
        try:
            await self._inner.edit(chat_id, message_id, rich_message, reply_markup)
        except MessageGone:
            lang = self._banner_lang(rich_message)
            if lang is None:
                raise
            await self._inner.edit(chat_id, message_id, self._with_text(rich_message, lang), reply_markup)
            await self._rejected(lang)

    def _banner_lang(self, rich_message: dict[str, Any]) -> Lang | None:
        blocks = rich_message.get("blocks") or []
        return self._banners.lang_of(blocks[0]) if blocks else None

    def _with_text(self, rich_message: dict[str, Any], lang: Lang) -> dict[str, Any]:
        return {**rich_message, "blocks": [self._banners.text_header(lang), *rich_message["blocks"][1:]]}

    async def _rejected(self, lang: Lang) -> None:
        logger.warning("Telegram не принял полосу {} — дальше строка, полоса загрузится заново", lang)
        await self._banners.forget(lang)
        if self.on_rejected is not None:
            await self.on_rejected()
