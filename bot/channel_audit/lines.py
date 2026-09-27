"""Факты → строки блоков отчёта (ТЗ, 6.1–6.4, 7.1). Строка — части абзаца: текст и ссылки словарями rich.link.

Факты в блоках — по одному на строку, каждая начинается с «> », со строчной буквы, без точки в конце.
"""
from datetime import date

from bot.channel_audit.formats import Formats
from bot.channel_audit.links import LinkHits, LinkSummary
from bot.channel_audit.rhythm import Gap, Rhythm
from bot.channel_audit.thresholds import GAP_DAYS
from bot.channel_audit.videos import Kind
from bot.channel_audit.views import BestVideo, GroupViews
from bot.channel_audit.wording import age, approx, approx_count, day_month, exact_count, round_half_up
from bot.core import rich
from bot.core.i18n import Lang, Texts

Line = list[str | dict]
LINE_MARK = "> "
LINE_BREAK = "\n"
WATCH_URL = "https://www.youtube.com/watch?v="
ONE = 1
SITE, TELEGRAM, WHATSAPP = "site", "telegram", "whatsapp"


def paragraph_of(lines: list[Line]) -> dict:
    parts: list[str | dict] = []
    for index, line in enumerate(lines):
        parts += [LINE_BREAK, LINE_MARK, *line] if index else [LINE_MARK, *line]
    return rich.paragraph(*parts)


def join_list(texts: Texts, lang: Lang, items: list[str]) -> str:
    """«a», «a и b», «a, b и c»."""
    if len(items) <= ONE:
        return "".join(items)
    return texts.get(lang, "list_comma").join(items[:-1]) + texts.get(lang, "list_and") + items[-1]


def rhythm_lines(texts: Texts, lang: Lang, rhythm: Rhythm, today: date) -> list[Line]:
    last = [texts.get(lang, "rhythm_last", age=age(texts, lang, rhythm.last_age_days),
                      date=day_month(lang, rhythm.last_published, today))]
    if rhythm.quiet:
        return [[texts.get(lang, "rhythm_quiet")], last]
    return [[_count_line(texts, lang, rhythm, today)], last, *_gap_lines(texts, lang, rhythm, today)]


def _count_line(texts: Texts, lang: Lang, rhythm: Rhythm, today: date) -> str:
    count = exact_count(lang, rhythm.count, "video")
    average = _average(texts, lang, rhythm.per_month)
    if rhythm.partial_since is None:
        return texts.get(lang, "rhythm_half_year", count=count, average=average)
    since = day_month(lang, rhythm.partial_since, today)
    return texts.get(lang, "rhythm_since", count=count, date=since, average=average)


def _average(texts: Texts, lang: Lang, per_month: float) -> str:
    if per_month < ONE:
        return texts.get(lang, "average_below_one")
    return texts.get(lang, "average_per_month", number=int(round_half_up(per_month)))


def _gap_lines(texts: Texts, lang: Lang, rhythm: Rhythm, today: date) -> list[Line]:
    """Перерыв до сегодня — всегда первым; из прошлых — один, самый длинный (ТЗ, 6.1)."""
    lines: list[Line] = []
    if rhythm.gap_to_now:
        days = exact_count(lang, rhythm.gap_to_now.days, "day")
        lines.append([texts.get(lang, "rhythm_gap_now", days_count=days)])
    if rhythm.past_gap:
        lines.append([_past_gap(texts, lang, rhythm.past_gap, today)])
    if not lines:
        lines.append([texts.get(lang, "rhythm_no_gaps", days_count=exact_count(lang, GAP_DAYS, "day"))])
    return lines


def _past_gap(texts: Texts, lang: Lang, gap: Gap, today: date) -> str:
    return texts.get(lang, "rhythm_gap_past", days_count=exact_count(lang, gap.days, "day"), days_number=gap.days,
                     start=day_month(lang, gap.start, today), end=day_month(lang, gap.end, today))


def views_lines(texts: Texts, lang: Lang, groups: tuple[GroupViews, ...]) -> list[Line]:
    """Сначала «обычно» по группам, потом лучшие видео — по одному на группу."""
    typical = [[_typical_line(texts, lang, group)] for group in groups]
    return typical + [_best_line(texts, lang, group.kind, group.best) for group in groups if group.best]


def _typical_line(texts: Texts, lang: Lang, group: GroupViews) -> str:
    name, typical = texts.get(lang, f"group_{group.kind}"), approx_count(lang, group.typical, "view")
    if group.recent is None:
        return texts.get(lang, "views_typical", group=name, typical=typical)
    key = "views_trend" if group.kind == Kind.SHORT else "views_trend_so_far"
    return texts.get(lang, key, group=name, typical=typical, recent=approx(lang, group.recent))


def _best_line(texts: Texts, lang: Lang, kind: Kind, best: BestVideo) -> Line:
    """Просмотры лучшего видео — точным числом API (ТЗ, Ю2); название — ссылкой на видео (ТЗ, Ю6)."""
    line: Line = [texts.get(lang, "views_best", group=texts.get(lang, f"group_{kind}_of")),
                  texts.get(lang, "quote_open"), rich.link(best.title, WATCH_URL + best.video_id),
                  texts.get(lang, "quote_close"),
                  texts.get(lang, "views_best_views", views=exact_count(lang, best.views, "view"))]
    if best.ratio:
        line.append(texts.get(lang, "views_best_ratio", times=exact_count(lang, best.ratio, "times")))
    return line


def formats_lines(texts: Texts, lang: Lang, formats: Formats) -> list[Line]:
    present = [(kind, count) for kind, count in formats.counts().items() if count]
    if len(present) == ONE and present[0][1] > ONE:
        kind, count = present[0]
        return [[texts.get(lang, "formats_all", count=count, kind=texts.get(lang, f"formats_all_{kind}"))]]
    return [[join_list(texts, lang, [_format_item(texts, lang, kind, count) for kind, count in present])]]


def _format_item(texts: Texts, lang: Lang, kind: Kind, count: int) -> str:
    item = exact_count(lang, count, str(kind))
    return item + texts.get(lang, "formats_short_note") if kind == Kind.SHORT else item


def links_lines(texts: Texts, lang: Lang, links: LinkSummary) -> list[Line]:
    lines: list[Line] = [[_channel_links(texts, lang, links.channel)]]
    if links.videos_checked:
        lines.append([_video_links(texts, lang, links)])
    return lines


def _channel_links(texts: Texts, lang: Lang, hits: LinkHits | None) -> str:
    if hits is None:
        return texts.get(lang, "links_channel_missing")
    names = [texts.get(lang, "links_site", domain=hits.sites[0])] if hits.sites else []
    names += [texts.get(lang, f"link_{name}") for name, found in ((TELEGRAM, hits.telegram),
                                                                   (WHATSAPP, hits.whatsapp)) if found]
    if not names:
        return texts.get(lang, "links_channel_none")
    return texts.get(lang, "links_channel", items=texts.get(lang, "list_comma").join(names))


def _video_links(texts: Texts, lang: Lang, links: LinkSummary) -> str:
    counts = ((SITE, links.site_videos), (TELEGRAM, links.telegram_videos), (WHATSAPP, links.whatsapp_videos))
    parts = [_present(texts, lang, name, count, links.top_site) for name, count in counts if count]
    absent = [texts.get(lang, f"link_{name}") for name, count in counts if not count]
    if absent:
        parts.append(texts.get(lang, "links_in_none", names=join_list(texts, lang, absent)))
    items = texts.get(lang, "list_comma").join(parts)
    if links.videos_checked == ONE:
        return texts.get(lang, "links_video_one", items=items)
    return texts.get(lang, "links_videos", count=links.videos_checked, items=items)


def _present(texts: Texts, lang: Lang, name: str, count: int, top_site: str | None) -> str:
    if name == SITE:
        return texts.get(lang, "links_in_site", count=count, domain=top_site)
    return texts.get(lang, "links_in", name=texts.get(lang, f"link_{name}"), count=count)
