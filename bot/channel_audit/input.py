"""Ввод человека → что искать на YouTube (ТЗ, раздел 4).

Присланную ссылку бот не открывает (ТЗ, В9): в Google уходят только ID, имя или старое имя, прошедшие проверку по
строгим правилам (ТЗ, В4). Процентные коды в пути раскрываются один раз — дважды закодированное имя не пройдёт.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

MAX_TEXT_LENGTH = 2000
HANDLE = "handle"
CHANNEL_ID = "channel_id"
USERNAME = "user"
LEGACY = "legacy"
VIDEO = "video"
NOT_A_LINK = "not_a_link"
NOT_YOUTUBE = "not_youtube"
PLAYLIST = "playlist"
HANDLE_MARK = "@"
SCHEME_MARK = "://"
DEFAULT_SCHEME = "https://"
TRAILING_PUNCTUATION = ".,;:!?)»\"'"
HANDLE_TRAILING = "."

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
SHORT_HOST = "youtu.be"
STUDIO_HOST = "studio.youtube.com"
STUDIO_CHANNEL = "channel"
VIDEO_SEGMENTS = frozenset({"shorts", "live", "embed", "v"})
PLAYLIST_SEGMENT = "playlist"
RESERVED_SEGMENTS = frozenset({
    "feed", "results", "playlist", "account", "premium", "gaming", "hashtag", "watch", "redirect", "about", "kids",
    "signin", "logout", "upload", "trending", "t", "ads", "creators", "yt", "jobs", "new", "podcasts", "sports",
    "news", "learning", "fashion", "post", "source", "attribution_link", "oembed", "howyoutubeworks", "music",
    "movies", "originals", "reporthistory",
})

CHANNEL_ID_PATTERN = re.compile(r"UC[0-9A-Za-z_-]{22}")
VIDEO_ID_PATTERN = re.compile(r"[0-9A-Za-z_-]{11}")
NAME_PATTERN = re.compile(r"[\w.\-·]{3,30}")
USERNAME_PATTERN = re.compile(r"[0-9A-Za-z]{1,40}")
URL_TOKEN = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?", re.IGNORECASE)
HANDLE_TOKEN = re.compile(r"(?<![\w.@/])@([\w.\-·]{3,30})")
PATH_TARGETS = {"channel": (CHANNEL_ID, CHANNEL_ID_PATTERN), "user": (USERNAME, USERNAME_PATTERN),
                "c": (LEGACY, NAME_PATTERN)}


@dataclass(frozen=True)
class Target:
    kind: str
    value: str
    bare: bool = False  # адрес youtube.com/ИМЯ: после имени пробуем старое имя (ТЗ, В3)

    @property
    def by_name(self) -> bool:
        """Канал из старого адреса найден по имени и может оказаться чужим (ТЗ, В10)."""
        return self.kind == LEGACY


@dataclass(frozen=True)
class Rejection:
    code: str


def parse_input(text: str, entity_urls: list[str]) -> Target | Rejection:
    """Сначала ссылки на YouTube (сущности Telegram, затем текст), потом первое @имя (ТЗ, В1)."""
    if len(text) > MAX_TEXT_LENGTH:
        return Rejection(NOT_A_LINK)
    urls = [*entity_urls, *_url_tokens(text)]
    parsed = [result for result in map(parse_url, urls) if result is not None]
    target = next((result for result in parsed if isinstance(result, Target)), None)
    if target is not None:
        return target
    handle = HANDLE_TOKEN.search(text)
    if handle:
        return _checked(HANDLE, handle.group(1).rstrip(HANDLE_TRAILING), NAME_PATTERN)
    if parsed:
        return parsed[0]
    return Rejection(NOT_YOUTUBE if urls else NOT_A_LINK)


def _url_tokens(text: str) -> list[str]:
    return [match.group().rstrip(TRAILING_PUNCTUATION) for match in URL_TOKEN.finditer(text)]


def parse_url(url: str) -> Target | Rejection | None:
    """None — ссылка не на YouTube."""
    parts = urlsplit(url if SCHEME_MARK in url else DEFAULT_SCHEME + url)
    host = (parts.hostname or "").lower()
    segments = [unquote(segment) for segment in parts.path.split("/") if segment]
    if host == SHORT_HOST:
        return _checked(VIDEO, segments[0] if segments else "", VIDEO_ID_PATTERN)
    if host == STUDIO_HOST:
        return _studio(segments)
    if host in YOUTUBE_HOSTS:
        return _youtube(segments, parse_qs(parts.query))
    return None


def _youtube(segments: list[str], query: dict[str, list[str]]) -> Target | Rejection:
    video = query.get("v", [""])[0]
    if video:
        return _checked(VIDEO, video, VIDEO_ID_PATTERN)
    if not segments:
        return Rejection(NOT_A_LINK)
    first, rest = segments[0], segments[1:]
    if first.startswith(HANDLE_MARK):
        return _checked(HANDLE, first.removeprefix(HANDLE_MARK), NAME_PATTERN)
    if first in VIDEO_SEGMENTS:
        return _checked(VIDEO, rest[0] if rest else "", VIDEO_ID_PATTERN)
    if first == PLAYLIST_SEGMENT:
        return Rejection(PLAYLIST)
    return _named(first, rest)


def _named(first: str, rest: list[str]) -> Target | Rejection:
    """/channel/…, /user/…, /c/… — по виду пути; /ИМЯ — только единственным сегментом и не служебным словом."""
    if first in PATH_TARGETS:
        kind, pattern = PATH_TARGETS[first]
        return _checked(kind, rest[0] if rest else "", pattern)
    if first in RESERVED_SEGMENTS or rest:
        return Rejection(NOT_A_LINK)
    return _checked(LEGACY, first, NAME_PATTERN, bare=True)


def _studio(segments: list[str]) -> Target | Rejection:
    """Студия — только /channel/UC…: владелец канала часто копирует адрес оттуда (ТЗ, В2)."""
    if len(segments) >= 2 and segments[0] == STUDIO_CHANNEL:
        return _checked(CHANNEL_ID, segments[1], CHANNEL_ID_PATTERN)
    return Rejection(NOT_A_LINK)


def _checked(kind: str, value: str, pattern: re.Pattern[str], bare: bool = False) -> Target | Rejection:
    return Target(kind, value, bare) if pattern.fullmatch(value) else Rejection(NOT_A_LINK)
