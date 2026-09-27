from datetime import timedelta

from bot.brand import BRAND
from bot.channel_audit.kv import Kv
from bot.channel_audit.notifier import DAY, OWNER_LANG, SIX_HOURS, Notifier
from bot.core.commands import simple_message
from bot.locales import TEXTS
from tests.fakes import ADMIN_ID, FakeClock, FakeMessenger, rich_text


def notifier(db, messenger: FakeMessenger, clock: FakeClock) -> Notifier:
    return Notifier(messenger, ADMIN_ID, clock, TEXTS, BRAND, Kv(db))


async def test_notification_is_the_shared_service_message(db):
    messenger = FakeMessenger()
    await notifier(db, messenger, FakeClock()).notify("banner", "notify_banner", DAY)
    expected = simple_message(TEXTS, OWNER_LANG, TEXTS.get("ru", "notify_banner"), BRAND)
    assert messenger.sent == [(ADMIN_ID, expected, None)]
    assert rich_text(expected).startswith(">jw ~/аудит-канала_\n")


async def test_pause_survives_a_restart(db):
    """Время последнего уведомления — в kv: перезапуск контейнера не засыпает личку заново."""
    messenger, clock = FakeMessenger(), FakeClock()
    await notifier(db, messenger, clock).notify("key", "notify_key", SIX_HOURS)
    clock.advance(timedelta(hours=5).total_seconds())
    await notifier(db, messenger, clock).notify("key", "notify_key", SIX_HOURS)
    assert len(messenger.sent) == 1
    clock.advance(timedelta(hours=2).total_seconds())
    await notifier(db, messenger, clock).notify("key", "notify_key", SIX_HOURS)
    assert len(messenger.sent) == 2


async def test_kinds_have_their_own_pauses(db):
    messenger = FakeMessenger()
    owner = notifier(db, messenger, FakeClock())
    await owner.notify("quota", "notify_quota", DAY, hours=5)
    await owner.notify("banner", "notify_banner", DAY)
    assert len(messenger.sent) == 2


class BrokenKv:
    async def get(self, key):
        raise RuntimeError("база недоступна")

    async def set(self, key, value):
        raise RuntimeError("база недоступна")


async def test_broken_database_keeps_the_pause_in_memory():
    messenger = FakeMessenger()
    owner = Notifier(messenger, ADMIN_ID, FakeClock(), TEXTS, BRAND, BrokenKv())
    await owner.notify("banner", "notify_banner", DAY)
    await owner.notify("banner", "notify_banner", DAY)
    assert len(messenger.sent) == 1


async def test_delivery_failure_is_logged_and_swallowed(db):
    messenger = FakeMessenger()
    messenger.blocked.add(ADMIN_ID)
    await notifier(db, messenger, FakeClock()).notify("banner", "notify_banner", DAY)  # без исключения
