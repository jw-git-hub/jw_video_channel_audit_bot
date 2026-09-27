"""Texts in English: first person, no emoji, the «>» marker (ТЗ, 7.1)."""

DECIMAL_SEPARATOR = "."
THOUSANDS_SEPARATOR = ","
MILLION_TEMPLATE = "{number}M"
UNITS = {"kb": "KB", "mb": "MB"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
WORDS = {
    "second": ("second", "seconds"),  # for the core: Texts.seconds
    "day": ("day", "days"),
    "month": ("month", "months"),
    "year": ("year", "years"),
    "video": ("video", "videos"),
    "view": ("view", "views"),
    "times": ("time", "times"),
    "short": ("short", "short"),
    "long": ("long", "long"),
    "live": ("live stream", "live streams"),
    "audit": ("audit", "audits"),
}
TEXTS = {
    "header_section": "channel-audit",
    "welcome": "Send me a link to a YouTube channel, its @handle or a link to any of its videos — I'll look at how "
               "often videos come out, how they're watched and where the descriptions send viewers. A plain-language "
               "report in a few seconds. No passwords or channel access needed.",
    "not_open_yet": "The bot opens soon — check back in a couple of days.",
    "legal_intro": "By sending a link, you accept the",
    "legal_terms": "YouTube Terms of Service",
    "legal_and": "and",
    "legal_privacy": "my privacy policy",
    "legal_end": ".",
    "lang_choose": "Choose a language.",
    "lang_done": "Done: I'll write in English.",
    "about": "I'm jw, and I made this bot. I build websites, Telegram bots and automation for what you still do "
             "by hand.",
    "about_site_button": "Website jw-dev.pro",
    "channel_button": "Channel",
    "order": "Message me directly with what you need — I'll reply myself.",
    "order_button": "Message @jw_dev_pro",
    "order_prefill": "From @jw_video_channel_audit_bot",
    "throttled": "Too fast — wait a couple of seconds.",
    "unexpected_error": "Something went wrong. Please try again.",
    "command_start": "Start",
    "command_lang": "Language",
    "command_about": "Who made this bot",
    "command_order": "How to order",
    "command_stats": "Stats",
    "command_channel": "Audits of a channel",
    "command_forget": "Delete a person's data",
}
