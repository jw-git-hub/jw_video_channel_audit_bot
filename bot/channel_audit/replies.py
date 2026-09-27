"""Служебные сообщения (ТЗ, 7.4): статус, отказы, ошибки. Все — статьи с шапкой бренда: полоса или строка.

Коды — строками, как в учёте (ТЗ, раздел 12): их производят разбор ввода, аудит, лимиты и приём — у каждого свои
константы. Тест задачи 20 сверяет, что у каждого кода, который можно получить, есть текст.
"""
from bot.core import rich
from bot.core.commands import Brand, simple_message
from bot.core.i18n import Lang, Texts

FALLBACK_CODE = "service_down"
FAILURE_CODES = (
    "not_a_link", "playlist", "not_text", "not_found", "legacy_not_found", "video_not_found", "service_down",
    "crowded", "limit_global", "interrupted",
)


def _simple(texts: Texts, lang: Lang, brand: Brand, key: str, **params: object) -> dict:
    return simple_message(texts, lang, texts.get(lang, key, **params), brand)


def checking(texts: Texts, lang: Lang, brand: Brand) -> dict:
    return _simple(texts, lang, brand, "checking")


def again(texts: Texts, lang: Lang, brand: Brand) -> dict:
    return _simple(texts, lang, brand, "again")


def busy(texts: Texts, lang: Lang, brand: Brand) -> dict:
    return _simple(texts, lang, brand, "busy")


def limit_user(texts: Texts, lang: Lang, brand: Brand, limit: int, hours: int) -> dict:
    return _simple(texts, lang, brand, "limit_user", audits=texts.count(lang, limit, "audit"), hours=hours)


def quota(texts: Texts, lang: Lang, brand: Brand, hours: int) -> dict:
    return _simple(texts, lang, brand, "quota", hours=hours)


def failure(texts: Texts, lang: Lang, brand: Brand, code: str) -> dict:
    return _simple(texts, lang, brand, code if code in FAILURE_CODES else FALLBACK_CODE)


def not_youtube(texts: Texts, lang: Lang, brand: Brand) -> tuple[dict, dict]:
    """Ссылка не на YouTube — всё равно повод поговорить о Telegram-канале (ТЗ, В6, 7.2)."""
    link = rich.dm_link(brand.dm_username, texts.get(lang, "order_prefill"))
    button = rich.button_url(texts.get(lang, "discuss_button"), link, rich.STYLE_PRIMARY)
    return _simple(texts, lang, brand, "not_youtube"), rich.keyboard(button)
