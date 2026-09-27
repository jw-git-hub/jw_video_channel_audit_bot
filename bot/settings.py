"""Настройки аудита видеоканала (ТЗ, раздел 16). Общие поля — в core.config.CoreSettings."""
from pydantic import PositiveInt

from bot.core.config import CoreSettings, NonEmptySecret


class Settings(CoreSettings):
    youtube_api_key: NonEmptySecret
    user_daily_limit: PositiveInt = 10
    global_daily_limit: PositiveInt = 500
    api_units_daily: PositiveInt = 8000
    audit_workers: PositiveInt = 3
