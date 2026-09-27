from bot.channel_audit.links import LinkHits, find_links, host_matches, summarize


def test_telegram_and_whatsapp_with_and_without_scheme():
    hits = find_links("Пишите: https://t.me/bike_rental_example и wa.me/84900000000, группа t.me/+AbCdEf")
    assert hits == LinkHits(telegram=True, whatsapp=True, sites=())


def test_site_is_named_by_domain_without_www_and_trailing_punctuation():
    hits = find_links("Цены: https://www.bike-rental-example.com/prices. Магазин: shop.bike-rental-example.com")
    assert hits.sites == ("bike-rental-example.com",)
    assert find_links("Сайт: www.bike-rental-example.com").sites == ("bike-rental-example.com",)


def test_subdomain_site_is_a_site_and_bare_domain_is_not_a_link():
    assert find_links("https://shop.bike-rental-example.com").sites == ("shop.bike-rental-example.com",)
    assert find_links("bike-rental-example.com").sites == ()


def test_platforms_messengers_and_shorteners_are_not_sites():
    text = ("https://instagram.com/x https://m.vk.com/y https://youtu.be/abc https://music.youtube.com/z "
            "https://bit.ly/q https://taplink.cc/z https://zalo.me/1 https://line.me/R/ti/p/a https://www.ozon.ru/p")
    assert find_links(text) == LinkHits()


def test_host_matches_itself_and_subdomains_only():
    assert host_matches("m.vk.com", ("vk.com",))
    assert host_matches("vk.com", ("vk.com",))
    assert not host_matches("notvk.com", ("vk.com",))


def test_repeated_sites_are_named_once():
    assert find_links("https://a-example.com https://b-example.com https://a-example.com/x").sites == (
        "a-example.com", "b-example.com")


def test_summary_counts_each_video_once_per_kind():
    videos = [LinkHits(telegram=True, sites=("a-example.com",)), LinkHits(sites=("a-example.com", "b-example.com")),
              LinkHits(whatsapp=True), LinkHits()]
    summary = summarize("Наш сайт https://a-example.com", videos)
    assert summary.channel == LinkHits(sites=("a-example.com",))
    assert (summary.videos_checked, summary.telegram_videos, summary.whatsapp_videos, summary.site_videos) == (
        4, 1, 1, 2)
    assert summary.top_site == "a-example.com"


def test_summary_of_a_channel_without_description():
    summary = summarize("   ", [])
    assert summary.channel is None
    assert (summary.videos_checked, summary.top_site) == (0, None)
