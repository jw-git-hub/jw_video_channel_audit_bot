"""Схема базы по версиям (ТЗ, раздел 12). Миграции только добавляющие: откат кода не ломает базу.

Из данных YouTube здесь только audits.channel_id и audits.handle — их обнуляет уборка через 20 дней
(bot/maintenance.py). Названий, описаний, ссылок и цифр каналов в базе нет (ТЗ, Ю4).
"""

MIGRATIONS = (
    (
        """CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT NOT NULL,
            lang_manual INTEGER NOT NULL DEFAULT 0,
            first_source TEXT NOT NULL,
            last_source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL)""",
        """CREATE TABLE audits (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            source TEXT NOT NULL,
            input_kind TEXT,
            channel_id TEXT,
            handle TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            from_cache INTEGER NOT NULL DEFAULT 0,
            charged INTEGER NOT NULL DEFAULT 0,
            api_units INTEGER NOT NULL DEFAULT 0,
            offered INTEGER NOT NULL DEFAULT 0,
            chat_id INTEGER,
            message_id INTEGER,
            created_at TEXT NOT NULL,
            finished_at TEXT)""",
        "CREATE INDEX audits_by_user_time ON audits(user_id, created_at)",
        "CREATE INDEX audits_by_time ON audits(created_at)",
        "CREATE INDEX audits_by_channel ON audits(channel_id, created_at)",
        "CREATE INDEX audits_by_handle ON audits(handle, created_at)",
        "CREATE INDEX audits_by_status ON audits(status)",
        """CREATE TABLE kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL)""",
    ),
)
