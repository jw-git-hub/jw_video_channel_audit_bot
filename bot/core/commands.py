"""Общие команды экосистемы (ТЗ, раздел 8): /start <метка>, /lang, /about, /order и меню команд.

Имя, описания, аватар и обложку бота код не трогает — только меню команд (setMyCommands).

Правка ядра 1 (аудит видеоканала, для jw_core): шапку сообщений даёт бренд — поставщиком Brand.header. Нет
поставщика — шапка прежняя, моноширинная строка из локали, как у сайт-чекера.

Правка ядра 2: у бренда могут быть правовые ссылки (Brand.terms_url, Brand.privacy_url) — тогда в приветствии
и /about есть абзац согласия «Присылая ссылку, вы принимаете [условия] и [политику]». Нет ссылок — нет абзаца.

Правка ядра 3: если у бренда есть правовые ссылки, /start до запуска показывает приветствие целиком — с абзацем
согласия, — а ниже «скоро откроется». Без ссылок до запуска — только «скоро откроется», как у чекера.
"""
import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, Message

from bot.core import rich
from bot.core.access import is_open_for
from bot.core.config import CoreSettings
from bot.core.i18n import RUSSIAN_CODES, Lang, Texts
from bot.core.messenger import Messenger, edit_or_send
from bot.core.stats import best_effort
from bot.core.users import Users, parse_label

LANG_CALLBACK_PREFIX = "lang:"
LANGUAGES: dict[str, str] = {"ru": "Русский", "en": "English"}
PUBLIC_COMMANDS = ("start", "lang", "about", "order")
DEFAULT_MENU_LANG: Lang = "en"
RUSSIAN_MENU_LANG: Lang = "ru"

HeaderBuilder = Callable[[Lang, str], dict]  # язык и раздел шапки → блок шапки


@dataclass(frozen=True)
class Brand:
    dm_username: str  # личка разработчика
    channel_url: str
    site_url: str
    header: HeaderBuilder | None = None  # шапка-картинка бота; нет — строка из локали
    terms_url: str | None = None  # условия площадки, которые человек принимает (у аудита — YouTube)
    privacy_url: str | None = None  # своя политика данных


router = Router(name="core_commands")


def page_header(texts: Texts, lang: Lang, brand: Brand | None = None) -> dict:
    section = texts.get(lang, "header_section")
    if brand is not None and brand.header is not None:
        return brand.header(lang, section)
    return rich.header(section)


def simple_message(texts: Texts, lang: Lang, text: str, brand: Brand | None = None) -> dict:
    return rich.message([page_header(texts, lang, brand), rich.paragraph(text)])


def lang_choice(texts: Texts, lang: Lang, brand: Brand | None = None) -> tuple[dict, dict]:
    buttons = [rich.button_callback(name, LANG_CALLBACK_PREFIX + code) for code, name in LANGUAGES.items()]
    message = rich.message([page_header(texts, lang, brand), rich.paragraph(texts.get(lang, "lang_choose"))])
    return message, rich.keyboard(*buttons)


def legal_paragraph(brand: Brand | None, texts: Texts, lang: Lang) -> dict | None:
    """Абзац согласия со ссылками. Нет правовых ссылок у бренда — нет абзаца (как у чекера)."""
    if brand is None or not (brand.terms_url and brand.privacy_url):
        return None
    return rich.paragraph(texts.get(lang, "legal_intro") + " ",
                          rich.link(texts.get(lang, "legal_terms"), brand.terms_url),
                          " " + texts.get(lang, "legal_and") + " ",
                          rich.link(texts.get(lang, "legal_privacy"), brand.privacy_url),
                          texts.get(lang, "legal_end"))


def start_message(brand: Brand, texts: Texts, lang: Lang, is_open: bool) -> dict:
    legal = legal_paragraph(brand, texts, lang)
    if not is_open and legal is None:
        return simple_message(texts, lang, texts.get(lang, "not_open_yet"), brand)
    blocks = [page_header(texts, lang, brand), rich.paragraph(texts.get(lang, "welcome"))]
    if legal is not None:
        blocks.append(legal)
    if not is_open:
        blocks.append(rich.paragraph(texts.get(lang, "not_open_yet")))
    return rich.message(blocks)


def about_message(brand: Brand, texts: Texts, lang: Lang) -> tuple[dict, dict]:
    legal = legal_paragraph(brand, texts, lang)
    blocks = [page_header(texts, lang, brand), rich.paragraph(texts.get(lang, "about")),
              *([legal] if legal else []), rich.divider(), rich.footer()]
    keyboard = rich.keyboard(rich.button_url(texts.get(lang, "about_site_button"), brand.site_url),
                             rich.button_url(texts.get(lang, "channel_button"), brand.channel_url))
    return rich.message(blocks), keyboard


def order_message(brand: Brand, texts: Texts, lang: Lang) -> tuple[dict, dict]:
    link = rich.dm_link(brand.dm_username, texts.get(lang, "order_prefill"))
    message = rich.message([page_header(texts, lang, brand), rich.paragraph(texts.get(lang, "order")),
                            rich.divider(), rich.footer()])
    keyboard = rich.keyboard(rich.button_url(texts.get(lang, "order_button"), link, rich.STYLE_PRIMARY))
    return message, keyboard


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, users: Users, messenger: Messenger, texts: Texts,
                   settings: CoreSettings, brand: Brand) -> None:
    user = await users.touch(message.from_user.id, message.from_user.language_code, parse_label(command.args))
    welcome = start_message(brand, texts, user.lang, is_open_for(settings, user.user_id))
    await messenger.send(message.chat.id, welcome)


@router.message(Command("lang"))
async def on_lang(message: Message, users: Users, messenger: Messenger, texts: Texts, brand: Brand) -> None:
    user = await users.touch(message.from_user.id, message.from_user.language_code)
    await messenger.send(message.chat.id, *lang_choice(texts, user.lang, brand))


@router.callback_query(F.data.startswith(LANG_CALLBACK_PREFIX))
async def on_lang_chosen(callback: CallbackQuery, users: Users, messenger: Messenger, texts: Texts,
                         brand: Brand) -> None:
    lang = callback.data.removeprefix(LANG_CALLBACK_PREFIX)
    # Устаревшее нажатие («query is too old») не должно ронять обработчик выбора языка.
    with contextlib.suppress(TelegramAPIError):
        await callback.answer()
    if lang not in LANGUAGES:
        return
    await best_effort(users.set_lang(callback.from_user.id, lang), "выбор языка", None)
    chat_id, message_id = callback.message.chat.id, callback.message.message_id
    done = simple_message(texts, lang, texts.get(lang, "lang_done"), brand)
    await edit_or_send(messenger, chat_id, message_id, done)


@router.message(Command("about"))
async def on_about(message: Message, users: Users, messenger: Messenger, texts: Texts, brand: Brand) -> None:
    user = await users.touch(message.from_user.id, message.from_user.language_code)
    await messenger.send(message.chat.id, *about_message(brand, texts, user.lang))


@router.message(Command("order"))
async def on_order(message: Message, users: Users, messenger: Messenger, texts: Texts, brand: Brand) -> None:
    user = await users.touch(message.from_user.id, message.from_user.language_code)
    await messenger.send(message.chat.id, *order_message(brand, texts, user.lang))


async def setup_commands(bot: Bot, texts: Texts, admin_id: int, admin_commands: tuple[str, ...]) -> None:
    """Меню на en для всех, на ru — для ru, uk, be, kk; владельцу — ещё свои команды."""
    await bot.set_my_commands(_menu(texts, DEFAULT_MENU_LANG, PUBLIC_COMMANDS))
    for code in sorted(RUSSIAN_CODES):
        await bot.set_my_commands(_menu(texts, RUSSIAN_MENU_LANG, PUBLIC_COMMANDS), language_code=code)
    owner_menu = _menu(texts, RUSSIAN_MENU_LANG, PUBLIC_COMMANDS + admin_commands)
    await bot.set_my_commands(owner_menu, scope=BotCommandScopeChat(chat_id=admin_id))


def _menu(texts: Texts, lang: Lang, names: tuple[str, ...]) -> list[BotCommand]:
    return [BotCommand(command=name, description=texts.get(lang, f"command_{name}")) for name in names]
