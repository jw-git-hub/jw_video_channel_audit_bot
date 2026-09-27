"""Ключ-значение в базе (ТЗ, раздел 12): file_id полос, счётчик единиц квоты, время уведомлений владельцу."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

GET = "SELECT value FROM kv WHERE key = :key"
SET = "INSERT INTO kv (key, value) VALUES (:key, :value) ON CONFLICT(key) DO UPDATE SET value = excluded.value"
DELETE = "DELETE FROM kv WHERE key = :key"


class Kv:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def get(self, key: str) -> str | None:
        async with self._engine.connect() as connection:
            return (await connection.execute(text(GET), {"key": key})).scalar()

    async def set(self, key: str, value: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(text(SET), {"key": key, "value": value})

    async def delete(self, key: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(text(DELETE), {"key": key})
