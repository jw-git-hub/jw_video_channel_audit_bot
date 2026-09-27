"""Числа, даты и давность словами (ТЗ, 6.1–6.2, 7.3) — одно место для отчёта и служебных сообщений.

Просмотры конкретного видео — точным числом API: руководство Google запрещает показывать число просмотров,
отличное от числа API (ТЗ, Ю2). Округляются только свои медианы: две значащие цифры, половина — вверх.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from bot.channel_audit.thresholds import AGE_IN_DAYS_UP_TO, AGE_IN_MONTHS_UP_TO, AVERAGE_MONTH_DAYS
from bot.core.i18n import Lang, Texts, plural_ru
from bot.locales import LOCALES

EXACT_BELOW = 100
MILLION = 1_000_000
SIGNIFICANT_DIGITS = 2
MILLION_DECIMALS = 1
DAYS_IN_YEAR = 365.25
YESTERDAY = 1
ONE = 1
DISPLAY_TIMEZONE = timezone(timedelta(hours=7))  # даты в отчёте — по UTC+7 (ТЗ, раздел 6)


def local_date(moment: datetime) -> date:
    return moment.astimezone(DISPLAY_TIMEZONE).date()


def round_half_up(value: float, decimals: int = 0) -> Decimal:
    """Половина — вверх: round() в Python округлил бы 2,5 до 2."""
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def word(lang: Lang, number: float, key: str) -> str:
    forms = LOCALES[lang].WORDS[key]
    if lang == "ru":
        return plural_ru(number, forms)
    return forms[0 if number == ONE else 1]


def exact(lang: Lang, number: int) -> str:
    """8437 → «8 437» (неразрывный пробел) или «8,437»."""
    return f"{number:,}".replace(",", LOCALES[lang].THOUSANDS_SEPARATOR)


def exact_count(lang: Lang, number: int, key: str) -> str:
    return f"{exact(lang, number)} {word(lang, number, key)}"


def approx_number(value: float) -> int:
    """Медиана для слова «около»: меньше 100 — целым, дальше — две значащие цифры; половина — вверх."""
    if value < EXACT_BELOW:
        return int(round_half_up(value))
    scale = 10 ** (len(str(int(value))) - SIGNIFICANT_DIGITS)
    return int(round_half_up(value / scale)) * scale


def approx(lang: Lang, value: float) -> str:
    """«1 200», «1,2 млн» / «1,200», «1.2M». Слово «около» ставит шаблон текста."""
    rounded = approx_number(value)
    if rounded < MILLION:
        return exact(lang, rounded)
    millions = round_half_up(value / MILLION, MILLION_DECIMALS).normalize()
    number = format(millions, "f").replace(".", LOCALES[lang].DECIMAL_SEPARATOR)
    return LOCALES[lang].MILLION_TEMPLATE.format(number=number)


def approx_count(lang: Lang, value: float, key: str) -> str:
    """«1 200 просмотров» — слово согласуется с округлённым числом."""
    return f"{approx(lang, value)} {word(lang, approx_number(value), key)}"


def day_month(lang: Lang, day: date, today: date) -> str:
    """«23 сентября»; год — только если он не совпадает с годом сбора: «14 марта 2025»."""
    text = f"{day.day} {LOCALES[lang].MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def age(texts: Texts, lang: Lang, days: int) -> str:
    """«сегодня», «вчера», «N дней назад» до 60 дней, «N месяцев назад» до 24 месяцев, дальше — годами."""
    if days < YESTERDAY:
        return texts.get(lang, "age_today")
    if days == YESTERDAY:
        return texts.get(lang, "age_yesterday")
    return texts.get(lang, "age_ago", amount=_age_amount(lang, days))


def _age_amount(lang: Lang, days: int) -> str:
    if days <= AGE_IN_DAYS_UP_TO:
        return exact_count(lang, days, "day")
    months = int(days // AVERAGE_MONTH_DAYS)
    if months < AGE_IN_MONTHS_UP_TO:
        return exact_count(lang, months, "month")
    return exact_count(lang, int(days // DAYS_IN_YEAR), "year")
