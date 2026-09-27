import dataclasses
from datetime import UTC, date, datetime, timedelta
from urllib.parse import unquote

from bot.brand import BRAND
from bot.channel_audit.ending import Ending, TelegramPlace
from bot.channel_audit.facts import Facts
from bot.channel_audit.formats import Formats
from bot.channel_audit.links import LinkHits, LinkSummary
from bot.channel_audit.report import AGAIN_CALLBACK, build_report
from bot.channel_audit.rhythm import Gap, Rhythm
from bot.channel_audit.videos import Kind
from bot.channel_audit.views import BestVideo, GroupViews
from bot.locales import TEXTS
from tests.builders import CHANNEL
from tests.fakes import rich_text

COLLECTED = datetime(2026, 9, 26, 5, tzinfo=UTC)  # 12:00 по UTC+7
NBSP = "\N{NO-BREAK SPACE}"


def photo(lang: str, section: str) -> dict:
    return {"type": "photo", "photo": {"type": "photo", "media": f"banner-{lang}"}}


BANNER_BRAND = dataclasses.replace(BRAND, header=photo)


def text_of(message: dict) -> str:
    return rich_text(message).replace(NBSP, " ")


def working() -> Facts:
    rhythm = Rhythm(COLLECTED - timedelta(days=182), 31, None, 31 / 6, date(2026, 9, 23), 3, None,
                    Gap(52, date(2026, 5, 2), date(2026, 6, 23)))
    views = (GroupViews(Kind.SHORT, 1234, 900, BestVideo("s1", "Байк за 5 минут", 25_310, 21)),
             GroupViews(Kind.LONG, 500, 450, BestVideo("l1", "Как выбрать байк в Дананге", 8437, 17)))
    links = LinkSummary(LinkHits(sites=("bikerental-example.com",)), 10, 0, 0, 7, "bikerental-example.com")
    return Facts(CHANNEL, "Байк-прокат Дананг", "@bike-rental-example", COLLECTED, links, rhythm, views,
                 Formats(18, 13, 0), Ending(True, 5, TelegramPlace.NOWHERE))


def sleeping() -> Facts:
    rhythm = Rhythm(COLLECTED - timedelta(days=182), 0, None, 0, date(2026, 1, 14), 255, None, None)
    links = LinkSummary(LinkHits(whatsapp=True, sites=("zerno-example.coffee",)), 10, 0, 0, 10,
                        "zerno-example.coffee")
    return Facts(CHANNEL, "Кофейня «Зерно»", "@zerno-coffee-example", COLLECTED, links, rhythm,
                 (GroupViews(Kind.LONG, 300, None, None),), None, Ending(False, 0, TelegramPlace.NOWHERE))


WORKING_RU = """[фото banner-ru]
Байк-прокат Дананг
youtube.com/@bike-rental-example
Ритм
> 31 видео за полгода, в среднем 5 в месяц
> последнее — 3 дня назад, 23 сентября
> перерыв 52 дня: с 2 мая по 23 июня
Отдача
> короткие обычно набирают около 1 200 просмотров, последние 10 — около 900
> длинные обычно набирают около 500 просмотров, последние 10 пока — около 450
> лучшее из коротких за полгода — «Байк за 5 минут», 25 310 просмотров, примерно в 21 раз больше обычного
> лучшее из длинных за полгода — «Как выбрать байк в Дананге», 8 437 просмотров, примерно в 17 раз больше обычного
Форматы
> 18 коротких (до 3 минут) и 13 длинных
Куда идёт зритель
> в описании канала — сайт bikerental-example.com
> в описаниях последних 10 видео: сайт — в 7 (bikerental-example.com), Telegram и WhatsApp — ни в одном
Что можно сделать
Сейчас вы выкладываете 5 видео в месяц. В описании канала и последних 10 видео нет ссылки на Telegram — зрителю, \
которому понравилось, некуда идти дальше. Каждое новое видео может само становиться постом в вашем Telegram-канале.
Подсчёты мои, по открытым данным YouTube на 26 сентября 2026. Ссылки искал в описании канала и в описаниях \
10 последних видео.
────
jw-dev.pro · @jw_dev_pro"""

SLEEPING_RU = """[фото banner-ru]
Кофейня «Зерно»
youtube.com/@zerno-coffee-example
Ритм
> за полгода новых видео не было
> последнее — 8 месяцев назад, 14 января
Отдача
> длинные обычно набирают около 300 просмотров
Куда идёт зритель
> в описании канала — сайт zerno-example.coffee, WhatsApp
> в описаниях последних 10 видео: сайт — в 10 (zerno-example.coffee), Telegram и WhatsApp — ни в одном
За последние 60 дней вышло меньше двух видео. Когда видео снова начнут выходить — пришлите канал ещё раз.
Подсчёты мои, по открытым данным YouTube на 26 сентября 2026. Ссылки искал в описании канала и в описаниях \
10 последних видео.
────
jw-dev.pro · @jw_dev_pro"""

WORKING_EN = """[фото banner-en]
Байк-прокат Дананг
youtube.com/@bike-rental-example
Rhythm
> 31 videos in six months, 5 a month on average
> the latest — 3 days ago, 23 September
> a 52-day gap: from 2 May to 23 June
Views
> short videos usually get about 1,200 views, the latest 10 — about 900
> long videos usually get about 500 views, the latest 10 so far — about 450
> the best short video in six months — "Байк за 5 минут", 25,310 views, about 21 times more than usual
> the best long video in six months — "Как выбрать байк в Дананге", 8,437 views, about 17 times more than usual
Formats
> 18 short (up to 3 minutes) and 13 long
Where viewers go
> the channel description links to a website, bikerental-example.com
> in the descriptions of the latest 10 videos: a website — in 7 (bikerental-example.com), Telegram and WhatsApp — \
in none
What you can do
Right now you post 5 videos a month. Neither the channel description nor the latest 10 videos link to Telegram — \
a viewer who liked a video has nowhere to go next. Every new video could become a post in your Telegram channel on \
its own.
My own calculations from public YouTube data as of 26 September 2026. I looked for links in the channel \
description and in the descriptions of the latest 10 videos.
────
jw-dev.pro · @jw_dev_pro"""


def test_working_channel_matches_the_spec_example_word_for_word():
    message, _ = build_report(TEXTS, "ru", BANNER_BRAND, working(), found_by_name=False)
    assert text_of(message) == WORKING_RU


def test_sleeping_channel_matches_the_spec_example_word_for_word():
    message, _ = build_report(TEXTS, "ru", BANNER_BRAND, sleeping(), found_by_name=False)
    assert text_of(message) == SLEEPING_RU


def test_english_report_keeps_titles_as_in_the_api():
    message, _ = build_report(TEXTS, "en", BANNER_BRAND, working(), found_by_name=False)
    assert text_of(message) == WORKING_EN


def test_titles_are_links_to_youtube_and_the_signature_is_italic():
    message, _ = build_report(TEXTS, "ru", BANNER_BRAND, working(), found_by_name=False)
    blocks = message["blocks"]
    assert blocks[2]["text"][0] == {"type": "url", "url": "https://www.youtube.com/@bike-rental-example",
                                    "text": "youtube.com/@bike-rental-example"}
    views = next(block for index, block in enumerate(blocks) if blocks[index - 1].get("text") == "Отдача")
    urls = [part["url"] for part in views["text"] if isinstance(part, dict)]
    assert urls == ["https://www.youtube.com/watch?v=s1", "https://www.youtube.com/watch?v=l1"]
    signature = blocks[-3]
    assert signature["text"][0]["type"] == "italic"


def test_keyboard_discusses_with_the_developer_about_this_channel():
    _, keyboard = build_report(TEXTS, "ru", BRAND, working(), found_by_name=False)
    discuss, again, channel = (row[0] for row in keyboard["inline_keyboard"])
    assert unquote(discuss["url"]) == "https://t.me/jw_dev_pro?text=Пришёл из аудита канала: @bike-rental-example"
    assert discuss["style"] == "primary"
    assert again["callback_data"] == AGAIN_CALLBACK
    assert channel["url"] == "https://t.me/jw_dev_pro_channel"


def test_channel_without_handle_is_named_by_its_address():
    facts = dataclasses.replace(working(), handle=None)
    message, keyboard = build_report(TEXTS, "ru", BRAND, facts, found_by_name=False)
    assert f"youtube.com/channel/{CHANNEL}" in text_of(message)
    assert unquote(keyboard["inline_keyboard"][0][0]["url"]).endswith(f"youtube.com/channel/{CHANNEL}")


def test_channel_found_by_name_says_so_under_the_link():
    message, _ = build_report(TEXTS, "ru", BRAND, working(), found_by_name=True)
    assert "youtube.com/@bike-rental-example\nНашёл по имени — если это не тот канал" in text_of(message)


def test_channel_without_public_videos_gets_the_short_report():
    links = LinkSummary(LinkHits(telegram=True), 0, 0, 0, 0, None)
    facts = Facts(CHANNEL, "Новый канал", "@new-example", COLLECTED, links)
    text = text_of(build_report(TEXTS, "ru", BRAND, facts, found_by_name=False)[0])
    assert text == (">jw ~/аудит-канала_\nНовый канал\nyoutube.com/@new-example\n> на канале пока нет открытых видео\n"
                    "Куда идёт зритель\n> в описании канала — Telegram\n"
                    "По открытым данным YouTube на 26 сентября 2026. Ссылки искал в описании канала.\n"
                    "────\njw-dev.pro · @jw_dev_pro")
