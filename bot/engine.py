"""Движок базы под политику данных этого бота (ТЗ, Сек7, Ю4): поверх ядра, без правки core/db.py.

- Параметры упавшего запроса не попадают в текст ошибки (и в журнал через logger.exception) — Docker хранит
  журнал месяцами, а без этого туда мог уйти ID канала или @имя (F1).
- Стёртые уборкой байты не остаются читаемыми в файле базы: PRAGMA secure_delete=ON на каждом соединении
  перезаписывает освобождённые страницы нулями (F2).
- В режиме WAL (core/db.py) secure_delete зачищает только страницу в bot.db-wal — старая страница с данными
  лежит в bot.db до автоконтрольной точки (~1000 кадров) или перезапуска. flush_deleted переносит и чистит
  сразу же: вызывается после уборки (bot/maintenance.py) и после AuditsRepo.forget_user (F2 в WAL-режиме).
"""
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.core.db import create_engine

SECURE_DELETE_PRAGMA = "PRAGMA secure_delete=ON"
WAL_CHECKPOINT_TRUNCATE_PRAGMA = "PRAGMA wal_checkpoint(TRUNCATE)"


def open_engine(data_dir: Path) -> AsyncEngine:
    engine = create_engine(data_dir)
    engine.sync_engine.hide_parameters = True
    event.listen(engine.sync_engine, "connect", _apply_secure_delete)
    return engine


async def flush_deleted(engine: AsyncEngine) -> None:
    """Контрольная точка WAL с TRUNCATE: переносит зачищенные secure_delete страницы в bot.db и обнуляет WAL."""
    async with engine.connect() as connection:
        await connection.execute(text(WAL_CHECKPOINT_TRUNCATE_PRAGMA))


def _apply_secure_delete(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute(SECURE_DELETE_PRAGMA)
    cursor.close()
