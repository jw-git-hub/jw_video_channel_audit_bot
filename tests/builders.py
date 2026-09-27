"""Сборщики входных данных для тестов. Каналы, @имена, названия и цифры — выдуманные (ТЗ, Сек13)."""
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.core.clock import to_iso

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
