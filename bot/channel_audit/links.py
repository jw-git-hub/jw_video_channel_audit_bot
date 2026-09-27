"""Ссылки в описаниях: Telegram, WhatsApp, сайт (ТЗ, 6.4). Ссылки не открываются — только разбираются.

Ссылка — адрес со схемой, адрес с www., а ещё t.me, telegram.me и wa.me без схемы. Голый example.com не считается:
YouTube такие ссылкой не делает. Соцсети, мессенджеры, площадки, сокращатели и визитки — «не сайт»: куда ведёт
сокращённая ссылка, не видно, а открывать её бот не будет.
"""
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

LINK_PATTERN = re.compile(
    r"https?://[^\s<>\"'()\[\]]+"
    r"|(?<![\w./@-])www\.[^\s<>\"'()\[\]]+"
    r"|(?<![\w./@-])(?:t\.me|telegram\.me|wa\.me)/[^\s<>\"'()\[\]]+",
    re.IGNORECASE)
TRAILING = ".,;:!?»…"
SCHEME_MARK = "://"
DEFAULT_SCHEME = "https://"
WWW_PREFIX = "www."
SUBDOMAIN_MARK = "."
TOP_ONE = 1
TELEGRAM_HOSTS = ("t.me", "telegram.me", "telegram.dog")
WHATSAPP_HOSTS = ("wa.me", "api.whatsapp.com", "chat.whatsapp.com", "whatsapp.com")
PLATFORM_HOSTS = (
    "youtube.com", "youtu.be", "google.com", "goo.gl", "instagram.com", "instagr.am", "ig.me", "facebook.com",
    "fb.com", "fb.me", "m.me", "vk.com", "vk.ru", "vk.me", "ok.ru", "tiktok.com", "x.com", "twitter.com",
    "threads.net", "linkedin.com", "pinterest.com", "twitch.tv", "discord.gg", "boosty.to", "patreon.com", "zalo.me",
    "line.me", "lin.ee", "viber.com", "max.ru", "dzen.ru", "rutube.ru", "ozon.ru", "wildberries.ru", "wb.ru",
    "avito.ru", "shopee.vn", "lazada.vn",
)
SHORTENER_HOSTS = ("bit.ly", "clck.ru", "vk.cc", "tinyurl.com", "cutt.ly", "taplink.cc", "taplink.ws", "linktr.ee")
NOT_SITES = TELEGRAM_HOSTS + WHATSAPP_HOSTS + PLATFORM_HOSTS + SHORTENER_HOSTS


@dataclass(frozen=True)
class LinkHits:
    telegram: bool = False
    whatsapp: bool = False
    sites: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkSummary:
    channel: LinkHits | None  # None — описания у канала нет
    videos_checked: int
    telegram_videos: int
    whatsapp_videos: int
    site_videos: int
    top_site: str | None


def host_matches(host: str, known: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith(SUBDOMAIN_MARK + item) for item in known)


def link_host(link: str) -> str:
    url = link.rstrip(TRAILING)
    host = (urlsplit(url if SCHEME_MARK in url else DEFAULT_SCHEME + url).hostname or "").lower()
    return host.removeprefix(WWW_PREFIX)


def find_links(text: str) -> LinkHits:
    hosts = [host for host in (link_host(match.group()) for match in LINK_PATTERN.finditer(text or "")) if host]
    sites = tuple(dict.fromkeys(host for host in hosts if not host_matches(host, NOT_SITES)))
    return LinkHits(any(host_matches(host, TELEGRAM_HOSTS) for host in hosts),
                    any(host_matches(host, WHATSAPP_HOSTS) for host in hosts), sites)


def summarize(channel_description: str, video_hits: list[LinkHits]) -> LinkSummary:
    """Описание канала и описания последних видео: сколько видео ведут в Telegram, WhatsApp, на сайт."""
    channel = find_links(channel_description) if channel_description.strip() else None
    sites = Counter(site for hits in video_hits for site in hits.sites)
    top = sites.most_common(TOP_ONE)
    return LinkSummary(channel, len(video_hits), sum(hits.telegram for hits in video_hits),
                       sum(hits.whatsapp for hits in video_hits), sum(bool(hits.sites) for hits in video_hits),
                       top[0][0] if top else None)
