import pytest

from bot.channel_audit.input import (CHANNEL_ID, HANDLE, LEGACY, NOT_A_LINK, NOT_YOUTUBE, PLAYLIST, USERNAME, VIDEO,
                                     Rejection, Target, parse_input)

CHANNEL = "UCabcdefghijABCDEFGHIJ12"
VIDEO_ID = "Ab3dE5gH1jK"


@pytest.mark.parametrize(("text", "expected"), [
    ("https://www.youtube.com/@BikeRentalExample", Target(HANDLE, "BikeRentalExample")),
    ("youtube.com/@bike.rental-example/videos", Target(HANDLE, "bike.rental-example")),
    ("мой канал @bike_rental_example, заходите", Target(HANDLE, "bike_rental_example")),
    (f"https://m.youtube.com/channel/{CHANNEL}", Target(CHANNEL_ID, CHANNEL)),
    (f"https://music.youtube.com/channel/{CHANNEL}", Target(CHANNEL_ID, CHANNEL)),
    (f"https://studio.youtube.com/channel/{CHANNEL}/videos/upload", Target(CHANNEL_ID, CHANNEL)),
    ("https://www.youtube.com/user/BikeRentalExample", Target(USERNAME, "BikeRentalExample")),
    ("https://www.youtube.com/c/BikeRentalExample/featured", Target(LEGACY, "BikeRentalExample")),
    ("https://www.youtube.com/BikeRentalExample", Target(LEGACY, "BikeRentalExample", bare=True)),
    (f"https://youtu.be/{VIDEO_ID}?t=10", Target(VIDEO, VIDEO_ID)),
    (f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PL123", Target(VIDEO, VIDEO_ID)),
    (f"https://www.youtube.com/shorts/{VIDEO_ID}", Target(VIDEO, VIDEO_ID)),
    (f"https://www.youtube.com/live/{VIDEO_ID}", Target(VIDEO, VIDEO_ID)),
    (f"https://www.youtube.com/embed/{VIDEO_ID}", Target(VIDEO, VIDEO_ID)),
    ("https://www.youtube.com/playlist?list=PL123", Rejection(PLAYLIST)),
    ("https://www.youtube.com/feed/subscriptions", Rejection(NOT_A_LINK)),
    ("https://www.youtube.com/", Rejection(NOT_A_LINK)),
    ("https://www.youtube.com/@ab", Rejection(NOT_A_LINK)),
    ("https://www.youtube.com/channel/UCshort", Rejection(NOT_A_LINK)),
    ("https://studio.youtube.com/video/Ab3dE5gH1jK/edit", Rejection(NOT_A_LINK)),
    ("https://www.instagram.com/bike_rental_example", Rejection(NOT_YOUTUBE)),
    ("привет", Rejection(NOT_A_LINK)),
    ("bike_rental_example", Rejection(NOT_A_LINK)),
])
def test_parse_input(text, expected):
    assert parse_input(text, []) == expected


def test_percent_encoded_cyrillic_handle_is_decoded_once():
    url = "https://www.youtube.com/@%D0%BA%D0%BE%D1%84%D0%B5%D0%B9%D0%BD%D1%8F"
    assert parse_input(url, []) == Target(HANDLE, "кофейня")
    twice_encoded = "https://www.youtube.com/@%25D0%25BA%25D0%25BE%25D1%2584"
    assert parse_input(twice_encoded, []) == Rejection(NOT_A_LINK)


def test_entity_link_goes_before_the_text():
    assert parse_input("посмотрите мой канал", [f"https://youtu.be/{VIDEO_ID}"]) == Target(VIDEO, VIDEO_ID)


def test_youtube_link_wins_over_other_links_and_handle_over_foreign_link():
    text = f"сайт bike-rental-example.com и канал https://youtu.be/{VIDEO_ID}"
    assert parse_input(text, []) == Target(VIDEO, VIDEO_ID)
    assert parse_input("сайт bike-rental-example.com, канал @bike_rental_example", []) == Target(HANDLE,
                                                                                                  "bike_rental_example")


def test_trailing_punctuation_is_not_part_of_the_link():
    assert parse_input(f"Вот: https://youtu.be/{VIDEO_ID}.", []) == Target(VIDEO, VIDEO_ID)


def test_email_is_not_a_handle():
    assert parse_input("пишите на mail@bike-rental-example.com", []) == Rejection(NOT_YOUTUBE)


def test_too_long_text_is_not_a_link():
    assert parse_input("a" * 2001, []) == Rejection(NOT_A_LINK)


def test_only_old_addresses_are_found_by_name():
    assert Target(LEGACY, "Name").by_name
    assert not Target(HANDLE, "Name").by_name
