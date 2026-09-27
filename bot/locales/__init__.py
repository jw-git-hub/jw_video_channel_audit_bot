"""Тексты бота на двух языках (ТЗ, Р11). LOCALES — модули целиком: формулировкам нужны слова и разделители."""
from bot.core.i18n import Texts
from bot.locales import en, ru

LOCALES = {"ru": ru, "en": en}
TEXTS = Texts(LOCALES)
