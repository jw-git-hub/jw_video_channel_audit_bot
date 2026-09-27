from datetime import date, timedelta

from bot.channel_audit.formats import Formats
from bot.channel_audit.lines import formats_lines, join_list, links_lines, rhythm_lines, views_lines
from bot.channel_audit.links import LinkHits, LinkSummary
from bot.channel_audit.rhythm import Gap, Rhythm
from bot.channel_audit.thresholds import ACTIVE_MIN_VIDEOS
from bot.channel_audit.videos import Kind
from bot.channel_audit.views import BestVideo, GroupViews
from bot.locales import TEXTS, en, ru
from tests.fakes import FAKE_NOW

TODAY = date(2026, 9, 26)
NBSP = "\N{NO-BREAK SPACE}"


def plain(lines) -> list[str]:
    texts = ("".join(part if isinstance(part, str) else part["text"] for part in line) for line in lines)
    return [text.replace(NBSP, " ") for text in texts]


def rhythm_of(count=31, partial_since=None, per_month=31 / 6, last=date(2026, 9, 23), age_days=3, gap_now=None,
              past=None) -> Rhythm:
    return Rhythm(FAKE_NOW - timedelta(days=182), count, partial_since, per_month, last, age_days, gap_now, past)


def test_capped_rhythm_says_since_when():
    rhythm = rhythm_of(200, date(2026, 7, 12), 200 / (75 / 30.4375), date(2026, 9, 26), 0)
    assert plain(rhythm_lines(TEXTS, "ru", rhythm, TODAY)) == [
        "200 видео с 12 июля, в среднем 81 в месяц", "последнее — сегодня, 26 сентября",
        "перерывов дольше 45 дней не было"]


def test_gap_to_today_goes_before_the_past_gap():
    rhythm = rhythm_of(3, None, 0.5, date(2026, 7, 28), 60, Gap(60, date(2026, 7, 28), None),
                       Gap(83, date(2026, 4, 28), date(2026, 7, 20)))
    assert plain(rhythm_lines(TEXTS, "ru", rhythm, TODAY)) == [
        "3 видео за полгода, меньше одного в месяц", "последнее — 60 дней назад, 28 июля",
        "новых видео нет уже 60 дней", "перерыв 83 дня: с 28 апреля по 20 июля"]


def test_quiet_rhythm_shows_only_the_last_video_with_its_year():
    rhythm = rhythm_of(0, None, 0, date(2025, 3, 14), 561)
    assert plain(rhythm_lines(TEXTS, "ru", rhythm, TODAY)) == [
        "за полгода новых видео не было", "последнее — 18 месяцев назад, 14 марта 2025"]


def test_english_rhythm():
    rhythm = rhythm_of(past=Gap(52, date(2026, 5, 2), date(2026, 6, 23)))
    assert plain(rhythm_lines(TEXTS, "en", rhythm, TODAY)) == [
        "31 videos in six months, 5 a month on average", "the latest — 3 days ago, 23 September",
        "a 52-day gap: from 2 May to 23 June"]


def test_views_line_without_trend_and_best_without_ratio():
    groups = (GroupViews(Kind.LIVE, 55.5, None, BestVideo("x", "Эфир", 120, None)),)
    lines = views_lines(TEXTS, "ru", groups)
    assert plain(lines) == ["трансляции обычно набирают около 56 просмотров",
                            "лучшее из трансляций за полгода — «Эфир», 120 просмотров"]
    assert lines[1][2] == {"type": "url", "url": "https://www.youtube.com/watch?v=x", "text": "Эфир"}


def test_formats_lines():
    assert plain(formats_lines(TEXTS, "ru", Formats(18, 13, 2))) == [
        "18 коротких (до 3 минут), 13 длинных и 2 трансляции"]
    assert plain(formats_lines(TEXTS, "ru", Formats(0, 12, 0))) == ["все 12 — длинные"]
    assert plain(formats_lines(TEXTS, "ru", Formats(0, 1, 0))) == ["1 длинное"]
    assert plain(formats_lines(TEXTS, "en", Formats(1, 0, 3))) == ["1 short (up to 3 minutes) and 3 live streams"]


def summary(channel=LinkHits(), checked=10, telegram=0, whatsapp=0, sites=0, top=None) -> LinkSummary:
    return LinkSummary(channel, checked, telegram, whatsapp, sites, top)


def test_links_lines_variants():
    assert plain(links_lines(TEXTS, "ru", summary(channel=None, checked=0))) == ["описания у канала нет"]
    assert plain(links_lines(TEXTS, "ru", summary(checked=1, telegram=1))) == [
        "в описании канала ссылок нет", "в описании последнего видео: Telegram — в 1, сайт и WhatsApp — ни в одном"]
    everything = summary(LinkHits(True, True, ("a-example.com",)), 4, 2, 1, 3, "a-example.com")
    assert plain(links_lines(TEXTS, "ru", everything)) == [
        "в описании канала — сайт a-example.com, Telegram, WhatsApp",
        "в описаниях последних 4 видео: сайт — в 3 (a-example.com), Telegram — в 2, WhatsApp — в 1"]
    assert plain(links_lines(TEXTS, "ru", summary()))[1] == (
        "в описаниях последних 10 видео: сайт, Telegram и WhatsApp — ни в одном")


def test_join_list():
    assert join_list(TEXTS, "ru", ["a"]) == "a"
    assert join_list(TEXTS, "ru", ["a", "b", "c"]) == "a, b и c"
    assert join_list(TEXTS, "en", ["a", "b"]) == "a and b"


def test_quiet_ending_text_matches_the_threshold():
    """«меньше двух видео» написано словом — порог и текст меняются вместе."""
    assert ACTIVE_MIN_VIDEOS == 2
    assert "меньше двух" in ru.TEXTS["ending_quiet"] and "Fewer than two" in en.TEXTS["ending_quiet"]
