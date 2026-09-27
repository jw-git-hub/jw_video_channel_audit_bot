"""Сборщики входных данных для тестов. Каналы, @имена, названия и цифры — выдуманные (ТЗ, Сек13)."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.channel_audit.collect import VIDEO_CHANNEL_FIELDS
from bot.channel_audit.links import LinkHits
from bot.channel_audit.videos import Video
from bot.core.clock import to_iso
from tests.fakes import FAKE_NOW

TEST_USER = 77

INSERT_USER = """
INSERT OR IGNORE INTO users (user_id, lang, lang_manual, first_source, last_source, created_at, last_seen_at)
VALUES (:user_id, 'ru', 0, 'direct', 'direct', :created_at, :created_at)"""
INSERT_AUDIT = """
INSERT INTO audits (user_id, source, input_kind, channel_id, handle, status, charged, api_units, created_at)
VALUES (:user_id, 'direct', 'handle', :channel_id, :handle, :status, :charged, :api_units, :created_at)"""


async def insert_audit(engine: AsyncEngine, created_at: datetime, channel_id: str | None = None,
                       handle: str | None = None, status: str = "done", charged: bool = True, api_units: int = 3,
                       user_id: int = TEST_USER) -> None:
    params = {"user_id": user_id, "channel_id": channel_id, "handle": handle, "status": status,
              "charged": int(charged), "api_units": api_units, "created_at": to_iso(created_at)}
    async with engine.begin() as connection:
        await connection.execute(text(INSERT_USER), params)
        await connection.execute(text(INSERT_AUDIT), params)


CHANNEL = "UCabcdefghijABCDEFGHIJ12"
UPLOADS = "UUabcdefghijABCDEFGHIJ12"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def iso(moment: datetime) -> str:
    return moment.strftime(ISO_FORMAT)


def days_ago(days: float) -> datetime:
    return FAKE_NOW - timedelta(days=days)


def channel_item(channel_id: str = CHANNEL, title: str = "Байк-прокат Пример", handle: str | None = "@bike-example",
                 description: str = "", uploads: str | None = UPLOADS) -> dict[str, Any]:
    snippet = {"title": title, "description": description, **({"customUrl": handle} if handle else {})}
    details = {"relatedPlaylists": {"uploads": uploads}} if uploads else {}
    return {"id": channel_id, "snippet": snippet, "contentDetails": details}


def page_entry(video_id: str, published: datetime | None) -> dict[str, Any]:
    details = {"videoId": video_id, **({"videoPublishedAt": iso(published)} if published else {})}
    return {"contentDetails": details}


def page(entries: list[dict[str, Any]], next_token: str | None = None) -> dict[str, Any]:
    return {"items": entries, **({"nextPageToken": next_token} if next_token else {})}


def video_item(video_id: str, published: datetime, duration: str = "PT10M", views: str | None = "100",
               live: bool = False, broadcast: str = "none", description: str = "",
               title: str = "Видео") -> dict[str, Any]:
    item = {"id": video_id, "snippet": {"publishedAt": iso(published), "title": title, "description": description,
                                        "liveBroadcastContent": broadcast},
            "contentDetails": {"duration": duration}, "statistics": {} if views is None else {"viewCount": views}}
    if live:
        item["liveStreamingDetails"] = {"actualStartTime": iso(published)}
    return item


class ScriptedClient:
    """Подделка YouTubeClient: отвечает заготовками по методу и ключевому параметру, считает единицы."""

    def __init__(self) -> None:
        self.channels: dict[str, dict[str, Any] | Exception] = {}
        self.video_channels: dict[str, dict[str, Any] | Exception] = {}
        self.pages: dict[str | None, dict[str, Any] | Exception] = {}
        self.videos: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def call(self, method: str, params: dict[str, str], deadline: float, meter) -> dict[str, Any]:
        self.calls.append((method, dict(params)))
        meter.units += 1
        answer = self._answer(method, params)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _answer(self, method: str, params: dict[str, str]) -> dict[str, Any] | Exception:
        if method == "channels":
            key = params.get("forHandle") or params.get("forUsername") or params.get("id")
            return self.channels.get(key, {"items": []})
        if method == "playlistItems":
            return self.pages.get(params.get("pageToken"), {"items": []})
        if params.get("fields") == VIDEO_CHANNEL_FIELDS:
            return self.video_channels.get(params["id"], {"items": []})
        return {"items": [self.videos[video_id] for video_id in params["id"].split(",") if video_id in self.videos]}

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


KIND_DURATIONS = {"short": 60, "long": 600, "live": 3600}


def video(days: float, kind: str = "long", views: int | None = 100, title: str = "Видео",
          links: LinkHits = LinkHits(), video_id: str | None = None, broadcast: str = "none") -> Video:
    """Видео, вышедшее days дней назад от FAKE_NOW."""
    return Video(video_id or f"v{days:g}", title, days_ago(days), KIND_DURATIONS[kind], views, kind == "live",
                 broadcast, links)
