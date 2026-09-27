from datetime import date

from bot.channel_audit.rhythm import Gap, rhythm
from bot.channel_audit.videos import usable
from tests.builders import video
from tests.fakes import FAKE_NOW


def test_weekly_channel_counts_half_a_year():
    videos = usable([video(1 + 7 * week) for week in range(40)])
    result = rhythm(videos, FAKE_NOW)
    assert (result.count, result.partial_since, result.quiet) == (26, None, False)
    assert result.per_month == 26 / 6
    assert (result.last_published, result.last_age_days) == (date(2026, 9, 24), 1)
    assert (result.gap_to_now, result.past_gap) == (None, None)


def test_capped_collection_counts_from_the_earliest_collected_video():
    """Канал с 2–3 видео в день: 200 видео — это 75 дней, а не полгода (ТЗ, 6.1)."""
    videos = usable([video(75 * index / 199, "short") for index in range(200)])
    result = rhythm(videos, FAKE_NOW)
    assert (result.count, result.partial_since) == (200, date(2026, 7, 12))
    assert round(result.per_month) == 81


def test_young_channel_divides_by_its_own_months_but_at_least_one():
    young = rhythm(usable([video(days) for days in (50, 40, 30, 20, 15, 10, 5, 1)]), FAKE_NOW)
    assert (young.count, young.partial_since) == (8, date(2026, 8, 6))
    assert round(young.per_month, 2) == 4.87
    newborn = rhythm(usable([video(days) for days in (10, 5, 1)]), FAKE_NOW)
    assert newborn.per_month == 3


def test_gap_to_today_and_longest_past_gap_inside_coverage():
    """Охват — с 27.03.2026. Видео 67 и 150 дней назад — 20.07 и 28.04: перерыв 83 дня, самый длинный."""
    videos = usable([video(67), video(150), video(200), video(260), video(310), video(400)])
    result = rhythm(videos, FAKE_NOW)
    assert result.count == 2
    assert result.gap_to_now == Gap(67, date(2026, 7, 20), None)
    assert result.past_gap == Gap(83, date(2026, 4, 28), date(2026, 7, 20))


def test_gap_that_ended_inside_the_coverage_counts_and_one_entirely_before_it_does_not():
    """Видео раз в 20 дней с 170 до 10 дней назад, до этого — 230 и 330 дней назад. Перерыв 230↔170 (60 дней)
    кончился внутри охвата и считается; 330↔230 (100 дней) целиком до охвата — нет."""
    videos = usable([video(days) for days in range(10, 171, 20)] + [video(230), video(330)])
    assert rhythm(videos, FAKE_NOW).past_gap == Gap(60, date(2026, 2, 7), date(2026, 4, 8))


def test_quiet_half_year_has_no_gaps():
    result = rhythm(usable([video(245), video(300)]), FAKE_NOW)
    assert (result.quiet, result.count, result.partial_since) == (True, 0, None)
    assert (result.gap_to_now, result.past_gap) == (None, None)
    assert result.last_age_days == 245
