"""Константы экосистемы для этого бота (ТЗ, 7.1–7.2, Ю7). Шапку-картинку ставит bot/app.py (задача 22)."""
from bot.core.commands import Brand

TERMS_URL = "https://www.youtube.com/t/terms"
PRIVACY_URL = "https://jw-dev.pro/privacy"

BRAND = Brand(dm_username="jw_dev_pro", channel_url="https://t.me/jw_dev_pro_channel", site_url="https://jw-dev.pro",
              terms_url=TERMS_URL, privacy_url=PRIVACY_URL)
