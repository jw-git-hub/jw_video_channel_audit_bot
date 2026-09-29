from datetime import date

import pytest

from bot.core.i18n import detect_lang, plural_ru
from bot.locales import TEXTS, en, ru

EMOJI_RANGES = ((0x2600, 0x27BF), (0xFE0F, 0xFE0F), (0x1F000, 0x1FAFF))
BUTTON_SUFFIX = "_button"
BUTTON_EMOJI = {"discuss_button": "💬", "another_button": "🔁", "channel_button": "📣",
                "about_site_button": "🌐", "order_button": "✉️"}


def has_emoji(text: str) -> bool:
    return any(low <= ord(char) <= high for char in text for low, high in EMOJI_RANGES)


@pytest.mark.parametrize(("code", "lang"), [
    ("ru", "ru"), ("uk", "ru"), ("be", "ru"), ("kk", "ru"), ("ru-RU", "ru"),
    ("en", "en"), ("vi", "en"), (None, "en"), ("", "en"),
])
def test_detect_lang(code, lang):
    assert detect_lang(code) == lang


@pytest.mark.parametrize(("number", "form"), [
    (1, "сайт"), (2, "сайта"), (5, "сайтов"), (11, "сайтов"), (21, "сайт"), (22, "сайта"), (112, "сайтов"), (1.4, "сайта"),
])
def test_plural_ru(number, form):
    assert plural_ru(number, ("сайт", "сайта", "сайтов")) == form


def test_seconds_below_ten_keep_one_decimal():
    assert TEXTS.seconds("ru", 1400) == "1,4 секунды"
    assert TEXTS.seconds("en", 1400) == "1.4 seconds"


def test_seconds_from_ten_are_whole_and_whole_numbers_have_no_zero():
    assert TEXTS.seconds("ru", 12_600) == "13 секунд"
    assert TEXTS.seconds("ru", 7000) == "7 секунд"


def test_sizes():
    assert TEXTS.size("ru", 265_789) == "260 КБ"
    assert TEXTS.size("ru", 3_355_443) == "3,2 МБ"
    assert TEXTS.size("en", 12 * 1024 * 1024) == "12 MB"


def test_sizes_at_the_kb_to_mb_boundary():
    assert TEXTS.size("ru", 1_022_976) == "999 КБ"
    assert TEXTS.size("ru", 1_024_000) == "1 МБ"
    assert TEXTS.size("ru", 1_048_575) == "1 МБ"
    assert TEXTS.size("en", 1_024_000) == "1 MB"


def test_dates():
    assert TEXTS.date("ru", date(2026, 12, 8)) == "8 декабря 2026"
    assert TEXTS.date("en", date(2026, 12, 8)) == "8 December 2026"


def test_count_words():
    assert TEXTS.count("ru", 2, "audit") == "2 аудита"
    assert TEXTS.count("en", 1, "audit") == "1 audit"


def test_locales_have_same_keys():
    assert ru.TEXTS.keys() == en.TEXTS.keys()
    assert ru.WORDS.keys() == en.WORDS.keys()


def test_texts_have_no_emoji_except_buttons():
    all_texts = [text for texts in (ru.TEXTS, en.TEXTS) for key, text in texts.items()
                 if not key.endswith(BUTTON_SUFFIX)]
    assert not [text for text in all_texts if has_emoji(text)]


@pytest.mark.parametrize("texts", [ru.TEXTS, en.TEXTS])
def test_every_button_starts_with_its_emoji(texts):
    buttons = {key: text for key, text in texts.items() if key.endswith(BUTTON_SUFFIX)}
    assert buttons.keys() == BUTTON_EMOJI.keys()
    assert all(text.startswith(BUTTON_EMOJI[key] + " ") for key, text in buttons.items())
