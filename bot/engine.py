"""Движок базы под политику данных этого бота (ТЗ, Сек7, Ю4): поверх ядра, без правки core/db.py.

- Параметры упавшего запроса не попадают в текст ошибки (и в журнал через logger.exception) — Docker хранит
  журнал месяцами, а без этого туда мог уйти ID канала или @имя (F1).
- Стёртые уборкой байты не остаются читаемыми в файле базы: PRAGMA secure_delete=ON на каждом соединении
  перезаписывает освобождённые страницы нулями (F2).
"""
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.core.db import create_engine

SECURE_DELETE_PRAGMA = "PRAGMA secure_delete=ON"


def open_engine(data_dir: Path) -> AsyncEngine:
    engine = create_engine(data_dir)
    engine.sync_engine.hide_parameters = True
    event.listen(engine.sync_engine, "connect", _apply_secure_delete)
    return engine


def _apply_secure_delete(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute(SECURE_DELETE_PRAGMA)
    cursor.close()
