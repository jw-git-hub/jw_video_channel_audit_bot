"""Факты → статья-отчёт (ТЗ, 7.1–7.3): полоса, название и ссылка на канал, блоки строками «> », вывод, подпись,
подвал и клавиатура под сообщением.

Подпись закрывает три правила YouTube: подсчёты отмечены как свои, источник — YouTube, данные — на дату сбора
(ТЗ, Ю2, Ю5, Ю6). Для кэша из вчерашних данных дата вчерашняя — так и должно быть.
"""
from datetime import date

from bot.channel_audit.facts import Facts
from bot.channel_audit.lines import (LINE_BREAK, ONE, Line, formats_lines, links_lines, paragraph_of, rhythm_lines,
                                     views_lines)
from bot.channel_audit.thresholds import ACTIVE_DAYS
from bot.channel_audit.wording import exact_count, local_date
from bot.core import rich
from bot.core.commands import Brand, page_header
from bot.core.i18n import Lang, Texts

TITLE_SIZE = 1
SECTION_SIZE = 2
AGAIN_CALLBACK = "again"
YOUTUBE_URL = "https://www.youtube.com/"
YOUTUBE_DISPLAY = "youtube.com/"
CHANNEL_PATH = "channel/"
ITALIC = "italic"
SENTENCE_JOIN = " "


def build_report(texts: Texts, lang: Lang, brand: Brand, facts: Facts, found_by_name: bool) -> tuple[dict, dict]:
    today = local_date(facts.collected_at)
    blocks = [page_header(texts, lang, brand), rich.heading(facts.title, TITLE_SIZE),
              _channel_paragraph(texts, lang, facts, found_by_name), *_sections(texts, lang, facts, today),
              *_ending(texts, lang, facts), _signature(texts, lang, facts, today), rich.divider(), rich.footer()]
    return rich.message(blocks), _keyboard(texts, lang, brand, facts)


def channel_address(facts: Facts) -> str:
    """«youtube.com/@имя», а без @имени — «youtube.com/channel/UC…» (ТЗ, 7.1–7.2)."""
    return YOUTUBE_DISPLAY + (facts.handle or CHANNEL_PATH + facts.channel_id)


def _channel_paragraph(texts: Texts, lang: Lang, facts: Facts, found_by_name: bool) -> dict:
    address = channel_address(facts)
    parts: list[str | dict] = [rich.link(address, YOUTUBE_URL + address.removeprefix(YOUTUBE_DISPLAY))]
    if found_by_name:
        parts += [LINE_BREAK, texts.get(lang, "found_by_name")]
    return rich.paragraph(*parts)


def _sections(texts: Texts, lang: Lang, facts: Facts, today: date) -> list[dict]:
    links = links_lines(texts, lang, facts.links)
    if not facts.has_videos:
        return [paragraph_of([[texts.get(lang, "no_videos")]]), *_section(texts, lang, "block_links", links)]
    formats = formats_lines(texts, lang, facts.formats) if facts.formats else []
    parts = (("block_rhythm", rhythm_lines(texts, lang, facts.rhythm, today)),
             ("block_views", views_lines(texts, lang, facts.views)), ("block_formats", formats), ("block_links", links))
    return [block for key, lines in parts if lines for block in _section(texts, lang, key, lines)]


def _section(texts: Texts, lang: Lang, key: str, lines: list[Line]) -> list[dict]:
    return [rich.heading(texts.get(lang, key), SECTION_SIZE), paragraph_of(lines)]


def _ending(texts: Texts, lang: Lang, facts: Facts) -> list[dict]:
    """Видео выходят — заголовок и три предложения; не выходят — одна строка без предложения пакета (ТЗ, 6.5)."""
    ending = facts.ending
    if ending is None:
        return []
    if not ending.active:
        return [rich.paragraph(texts.get(lang, "ending_quiet", days_count=exact_count(lang, ACTIVE_DAYS, "day")))]
    sentences = (texts.get(lang, "ending_pace", videos=exact_count(lang, ending.pace, "video")),
                 texts.get(lang, f"ending_tg_{ending.telegram}", count=facts.links.videos_checked),
                 texts.get(lang, "ending_offer"))
    return [rich.heading(texts.get(lang, "ending_title"), SECTION_SIZE), rich.paragraph(SENTENCE_JOIN.join(sentences))]


def _signature(texts: Texts, lang: Lang, facts: Facts, today: date) -> dict:
    day, checked = texts.date(lang, today), facts.links.videos_checked
    if not facts.has_videos:
        text = texts.get(lang, "signature_no_videos", date=day)
    else:
        text = texts.get(lang, "signature_one" if checked == ONE else "signature", date=day, count=checked)
    return rich.paragraph({"type": ITALIC, "text": text})


def _keyboard(texts: Texts, lang: Lang, brand: Brand, facts: Facts) -> dict:
    prefill = texts.get(lang, "discuss_prefill", channel=facts.handle or channel_address(facts))
    discuss = rich.button_url(texts.get(lang, "discuss_button"), rich.dm_link(brand.dm_username, prefill),
                              rich.STYLE_PRIMARY)
    return rich.keyboard(discuss, rich.button_callback(texts.get(lang, "another_button"), AGAIN_CALLBACK),
                         rich.button_url(texts.get(lang, "channel_button"), brand.channel_url))
