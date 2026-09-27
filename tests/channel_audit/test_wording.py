from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from bot.channel_audit.wording import (age, approx, approx_count, day_month, exact, exact_count, local_date,
                                       round_half_up, word)
from bot.locales import TEXTS

NBSP = "\N{NO-BREAK SPACE}"


def test_local_date_is_by_utc_plus_seven():
    assert local_date(datetime(2026, 9, 25, 18, tzinfo=UTC)) == date(2026, 9, 26)
    assert local_date(datetime(2026, 9, 25, 16, tzinfo=UTC)) == date(2026, 9, 25)


def test_round_half_up_rounds_the_half_up():
    assert round_half_up(2.5) == 3
    assert round_half_up(16.874) == 17
    assert round_half_up(1.25, 1) == Decimal("1.3")


@pytest.mark.parametrize(("number", "ru", "en"), [(8437, "8 437", "8,437"), (25_310, "25 310", "25,310"),
                                                  (7, "7", "7")])
def test_exact_numbers_keep_every_digit(number, ru, en):
    assert exact("ru", number) == ru.replace(" ", NBSP)
    assert exact("en", number) == en


@pytest.mark.parametrize(("value", "ru"), [
    (45.5, "46"), (99.4, "99"), (455, "460"), (1234, "1 200"), (1250, "1 300"), (995, "1 000"),
    (123_456, "120 000"), (999_600, "1 млн"), (1_234_567, "1,2 млн"), (2_000_000, "2 млн"),
])
def test_approx_rounds_medians_to_two_significant_digits(value, ru):
    assert approx("ru", value) == ru.replace(" ", NBSP)


def test_approx_in_english():
    assert approx("en", 1234) == "1,200"
    assert approx("en", 1_234_567) == "1.2M"


@pytest.mark.parametrize(("number", "form"), [(1, "раз"), (2, "раза"), (5, "раз"), (17, "раз"), (21, "раз"),
                                              (22, "раза")])
def test_times_word(number, form):
    assert word("ru", number, "times") == form


def test_counts_with_words():
    assert exact_count("ru", 8437, "view") == f"8{NBSP}437 просмотров"
    assert exact_count("ru", 1, "view") == "1 просмотр"
    assert exact_count("ru", 22, "view") == "22 просмотра"
    assert exact_count("en", 1, "view") == "1 view"
    assert approx_count("ru", 1234, "view") == f"1{NBSP}200 просмотров"


def test_dates_show_the_year_only_when_it_differs():
    today = date(2026, 9, 26)
    assert day_month("ru", date(2026, 9, 23), today) == "23 сентября"
    assert day_month("ru", date(2025, 3, 14), today) == "14 марта 2025"
    assert day_month("en", date(2026, 5, 2), today) == "2 May"


@pytest.mark.parametrize(("days", "ru"), [
    (0, "сегодня"), (1, "вчера"), (3, "3 дня назад"), (60, "60 дней назад"), (61, "2 месяца назад"),
    (255, "8 месяцев назад"), (800, "2 года назад"),
])
def test_age_in_words(days, ru):
    assert age(TEXTS, "ru", days) == ru


def test_age_in_english():
    assert age(TEXTS, "en", 3) == "3 days ago"
    assert age(TEXTS, "en", 1) == "yesterday"
