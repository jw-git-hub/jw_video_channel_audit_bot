"""Канал и его видео из YouTube Data API (ТЗ, 5.1): поиск канала, листание плейлиста загрузок, пачки по 50.

Плейлист загрузок — из contentDetails.relatedPlaylists.uploads, как записано в документации; заменой UC на UU
не пользуемся, скрытые UUSH и UULF не трогаем (ТЗ, Ю11). Описания видео нужны только для ссылок: они разбираются
сразу, дальше идёт только итог — LinkHits.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bot.channel_audit.input import CHANNEL_ID, HANDLE, LEGACY, USERNAME, VIDEO, Target
from bot.channel_audit.links import find_links
from bot.channel_audit.thresholds import BASELINE_DAYS, MAX_VIDEOS
from bot.channel_audit.videos import NOT_A_BROADCAST, Video, duration_seconds
from bot.channel_audit.youtube import SHAPE, Meter, NotFound, ServiceDown, YouTubeClient
from bot.core.clock import Clock

CHANNELS = "channels"
VIDEOS = "videos"
PLAYLIST_ITEMS = "playlistItems"
CHANNEL_FIELDS = "items(id,snippet(title,description,customUrl),contentDetails/relatedPlaylists/uploads)"
VIDEO_CHANNEL_FIELDS = "items/snippet/channelId"
PAGE_FIELDS = "nextPageToken,items/contentDetails(videoId,videoPublishedAt)"
VIDEO_FIELDS = ("items(id,snippet(publishedAt,title,description,liveBroadcastContent),contentDetails/duration,"
                "statistics/viewCount,liveStreamingDetails)")
CHANNEL_PARTS = "snippet,contentDetails"
VIDEO_PARTS = "snippet,contentDetails,statistics,liveStreamingDetails"
PAGE_SIZE = "50"
BATCH_SIZE = 50
MAX_PAGES = MAX_VIDEOS // BATCH_SIZE + 1  # страница сверх 200 видео — на случай пересечения границы в 12 месяцев
ID_SEPARATOR = ","
HANDLE_MARK = "@"
BY_HANDLE = "forHandle"
BY_USERNAME = "forUsername"
BY_ID = "id"
LOOKUPS = {HANDLE: BY_HANDLE, LEGACY: BY_HANDLE, USERNAME: BY_USERNAME, CHANNEL_ID: BY_ID}
LIVE_DETAILS = "liveStreamingDetails"


class ChannelNotFound(Exception):
    """Канала нет. args[0] — вид ввода: какой отказ показать, решает он (ТЗ, 5.3)."""


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    title: str
    handle: str | None  # customUrl из API — «@имя», если оно есть
    description: str
    uploads: str | None


class Collector:
    def __init__(self, client: YouTubeClient, clock: Clock):
        self._client = client
        self._clock = clock

    async def find_channel(self, target: Target, deadline: float, meter: Meter) -> ChannelInfo:
        if target.kind == VIDEO:
            return await self._by_video(target.value, deadline, meter)
        parameter = LOOKUPS[target.kind]
        value = HANDLE_MARK + target.value if parameter == BY_HANDLE else target.value
        found = await self._lookup(parameter, value, deadline, meter)
        if found is None and target.bare:
            found = await self._lookup(BY_USERNAME, target.value, deadline, meter)
        if found is None:
            raise ChannelNotFound(target.kind)
        return found

    async def videos(self, uploads: str | None, deadline: float, meter: Meter) -> list[Video]:
        if not uploads:
            return []
        ids = await self._upload_ids(uploads, deadline, meter)
        videos: list[Video] = []
        for start in range(0, len(ids), BATCH_SIZE):
            videos += await self._details(ids[start:start + BATCH_SIZE], deadline, meter)
        return videos

    async def _lookup(self, parameter: str, value: str, deadline: float, meter: Meter) -> ChannelInfo | None:
        params = {"part": CHANNEL_PARTS, parameter: value, "fields": CHANNEL_FIELDS}
        try:
            items = _items(await self._client.call(CHANNELS, params, deadline, meter))
        except NotFound:
            return None
        return _channel(items[0]) if items else None

    async def _by_video(self, video_id: str, deadline: float, meter: Meter) -> ChannelInfo:
        params = {"part": "snippet", "id": video_id, "fields": VIDEO_CHANNEL_FIELDS}
        try:
            items = _items(await self._client.call(VIDEOS, params, deadline, meter))
        except NotFound:
            items = []
        channel_id = _text(items[0], "snippet", "channelId") if items else ""
        if not channel_id:
            raise ChannelNotFound(VIDEO)
        found = await self._lookup(BY_ID, channel_id, deadline, meter)
        if found is None:
            raise ChannelNotFound(CHANNEL_ID)
        return found

    async def _upload_ids(self, uploads: str, deadline: float, meter: Meter) -> list[str]:
        """Страницы по 50 — до 200 видео или до 12 месяцев; после границы ещё одна, если есть место (ТЗ, 5.1).

        Не больше MAX_PAGES вовсе: без этого сплошь недатированный плейлист листался бы до самого срока
        аудита — дата считается только у части записей, счёт по ним не растёт (F7)."""
        cutoff = self._clock.now() - timedelta(days=BASELINE_DAYS)
        ids: list[str] = []
        token, crossed = None, False
        for _ in range(MAX_PAGES):
            page = await self._page(uploads, token, deadline, meter)
            entries = [entry for entry in map(_entry, _items(page)) if entry]
            ids += [video_id for video_id, _ in entries]
            token = page.get("nextPageToken")
            if len(ids) >= MAX_VIDEOS or not token or crossed:
                return ids[:MAX_VIDEOS]
            crossed = any(published < cutoff for _, published in entries)
        return ids[:MAX_VIDEOS]

    async def _page(self, uploads: str, token: str | None, deadline: float, meter: Meter) -> dict[str, Any]:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": PAGE_SIZE, "fields": PAGE_FIELDS}
        if token:
            params["pageToken"] = token
        try:
            return await self._client.call(PLAYLIST_ITEMS, params, deadline, meter)
        except NotFound:
            return {}  # плейлист пуст или его нет (404 playlistNotFound) — короткий отчёт (ТЗ, 6.6)

    async def _details(self, ids: list[str], deadline: float, meter: Meter) -> list[Video]:
        """4xx на пачку ID — про сами видео между листанием и запросом, не про присланное (ТЗ, Л5; F9)."""
        params = {"part": VIDEO_PARTS, "id": ID_SEPARATOR.join(ids), "fields": VIDEO_FIELDS}
        try:
            payload = await self._client.call(VIDEOS, params, deadline, meter)
        except NotFound:
            raise ServiceDown(SHAPE) from None
        return [video for video in map(_video, _items(payload)) if video]


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ServiceDown(SHAPE)
    return [item for item in items if isinstance(item, dict)]


def _text(raw: dict[str, Any], *path: str) -> str:
    value: Any = raw
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else ""


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _entry(raw: dict[str, Any]) -> tuple[str, datetime] | None:
    """ID и дата выхода со страницы плейлиста; закрытые и удалённые видео приходят без даты — не в счёт."""
    video_id = _text(raw, "contentDetails", "videoId")
    published = _time(_text(raw, "contentDetails", "videoPublishedAt"))
    return (video_id, published) if video_id and published else None


def _channel(raw: dict[str, Any]) -> ChannelInfo:
    channel_id = raw.get("id")
    if not isinstance(channel_id, str) or not channel_id:
        raise ServiceDown(SHAPE)
    uploads = _text(raw, "contentDetails", "relatedPlaylists", "uploads")
    return ChannelInfo(channel_id, _text(raw, "snippet", "title"), _text(raw, "snippet", "customUrl") or None,
                       _text(raw, "snippet", "description"), uploads or None)


def _video(raw: dict[str, Any]) -> Video | None:
    video_id = raw.get("id")
    published = _time(_text(raw, "snippet", "publishedAt"))
    if not isinstance(video_id, str) or published is None:
        return None
    return Video(video_id, _text(raw, "snippet", "title"), published,
                 duration_seconds(_text(raw, "contentDetails", "duration")), _views(raw), LIVE_DETAILS in raw,
                 _text(raw, "snippet", "liveBroadcastContent") or NOT_A_BROADCAST,
                 find_links(_text(raw, "snippet", "description")))


def _views(raw: dict[str, Any]) -> int | None:
    value = _text(raw, "statistics", "viewCount")
    return int(value) if value.isdigit() else None
