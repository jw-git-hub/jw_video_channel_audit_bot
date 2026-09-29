import dataclasses
from urllib.parse import unquote

import pytest

from bot.brand import BRAND
from bot.channel_audit import replies
from bot.locales import TEXTS, en, ru
from tests.fakes import rich_text

CLAIMS = ("официальн", "партнёр", "партнер", "official", "partner")


def photo(lang: str, section: str) -> dict:
    return {"type": "photo", "photo": {"type": "photo", "media": f"banner-{lang}"}}


def test_checking_is_an_article_with_the_header():
    assert rich_text(replies.checking(TEXTS, "ru", BRAND)) == ">jw ~/аудит-канала_\nСмотрю канал…"
    assert rich_text(replies.checking(TEXTS, "en", BRAND)) == ">jw ~/channel-audit_\nLooking at the channel…"


def test_replies_carry_the_banner_when_the_brand_has_one():
    brand = dataclasses.replace(BRAND, header=photo)
    assert rich_text(replies.again(TEXTS, "ru", brand)).startswith("[фото banner-ru]\nПришлите ссылку")


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("code", replies.FAILURE_CODES)
def test_every_failure_has_text_in_both_languages(lang, code):
    text = rich_text(replies.failure(TEXTS, lang, BRAND, code))
    assert text.startswith(">jw ~/" + TEXTS.get(lang, "header_section") + "_\n")
    assert "{" not in text


def test_unknown_failure_code_falls_back_to_service_down():
    assert "Данные YouTube сейчас недоступны" in rich_text(replies.failure(TEXTS, "ru", BRAND, "что-то новое"))


def test_limit_user_counts_audits_and_hours():
    assert rich_text(replies.limit_user(TEXTS, "ru", BRAND, 10, 3)).endswith(
        "Лимит — 10 аудитов в сутки. Следующий будет доступен через 3 ч.")
    assert rich_text(replies.limit_user(TEXTS, "en", BRAND, 10, 3)).endswith(
        "The limit is 10 audits a day. The next one will be available in 3 h.")


def test_quota_says_when_youtube_data_comes_back():
    assert "откроются через 5 ч. Попытка не потрачена." in rich_text(replies.quota(TEXTS, "ru", BRAND, 5))


def test_not_youtube_offers_to_talk_to_the_developer():
    message, keyboard = replies.not_youtube(TEXTS, "ru", BRAND)
    assert "Это не YouTube." in rich_text(message)
    button = keyboard["inline_keyboard"][0][0]
    assert (button["text"], button["style"]) == ("💬 Обсудить с разработчиком", "primary")
    assert unquote(button["url"]) == "https://t.me/jw_dev_pro?text=Пришёл из @jw_video_channel_audit_bot"


def test_busy_and_interrupted():
    assert "Сначала закончу с этим каналом" in rich_text(replies.busy(TEXTS, "ru", BRAND))
    assert "Аудит прервался" in rich_text(replies.failure(TEXTS, "ru", BRAND, "interrupted"))


def test_texts_never_claim_to_be_official_or_a_partner():
    """Бот не называет себя официальным и не намекает на партнёрство с YouTube (ТЗ, Ю8) — во всех текстах."""
    for locale in (ru, en):
        assert not [text for text in locale.TEXTS.values() if any(claim in text.lower() for claim in CLAIMS)]
