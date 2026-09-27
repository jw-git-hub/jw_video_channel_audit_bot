from aiogram.filters import CommandObject
from sqlalchemy import text

from bot.brand import BRAND
from bot.channel_audit.admin import ChannelQuery, IsAdmin, channel_query, on_channel, on_forget, on_stats
from bot.channel_audit.audits import DONE, FAILED, RUNNING, AuditsRepo, Closing, NewAudit
from bot.channel_audit.kv import Kv
from bot.channel_audit.quota import QuotaGate
from bot.core.users import Users
from bot.locales import TEXTS
from tests.builders import CHANNEL
from tests.fakes import ADMIN_ID, FakeClock, FakeMessenger, make_message

USER = 77
OTHER = 78


async def fill(db) -> AuditsRepo:
    clock = FakeClock()
    await Users(db, clock).touch(USER, "ru", "channel")
    await Users(db, clock).touch(OTHER, "en", "fb")
    repo = AuditsRepo(db, clock)
    audit_id = await repo.create(NewAudit(USER, "channel", "handle", RUNNING, chat_id=USER, message_id=5))
    await repo.finish(audit_id, Closing(DONE, channel_id=CHANNEL, handle="@bike-example", charged=True, api_units=3,
                                        offered=True))
    await repo.create(NewAudit(OTHER, "fb", None, FAILED, "not_a_link"))
    return repo


def command(name: str, args: str | None) -> CommandObject:
    return CommandObject(command=name, args=args)


async def ask_channel(repo: AuditsRepo, messenger: FakeMessenger, args: str) -> str:
    await on_channel(make_message("/channel", user_id=ADMIN_ID), command("channel", args), repo=repo,
                     messenger=messenger, texts=TEXTS, brand=BRAND, clock=FakeClock())
    return messenger.last()


async def test_stats_by_label_with_quota_units(db):
    messenger, clock = FakeMessenger(), FakeClock()
    quota = QuotaGate(Kv(db), clock, ceiling=8000)
    await quota.spend(42)
    await on_stats(make_message("/stats", user_id=ADMIN_ID), repo=await fill(db), quota=quota, messenger=messenger,
                   texts=TEXTS, brand=BRAND, clock=clock)
    report = messenger.last()
    assert "Учёт за 7 дней" in report and "Учёт за 30 дней" in report
    assert "channel | 1 | 1 | 1 | 0 | 1 | 0" in report
    assert "fb | 1 | 0 | 1 | 0 | 0 | 1" in report
    assert "Отказы: not_a_link — 1." in report
    assert "Единиц квоты за сутки по тихоокеанскому времени: 42 из 8000." in report
    assert report.endswith("Откуда человек — /channel @имя.")


async def test_channel_by_handle_in_any_case_and_by_link(db):
    repo, messenger = await fill(db), FakeMessenger()
    for args in ("@Bike-Example", f"https://www.youtube.com/channel/{CHANNEL}"):
        assert "25.09 19:00 | channel | done | нет | да" in await ask_channel(repo, messenger, args)


async def test_channel_without_audits_and_video_links(db):
    repo, messenger = await fill(db), FakeMessenger()
    assert "Аудитов этого канала за 20 дней нет." in await ask_channel(repo, messenger, "@nobody-example")
    assert "Пришлите @имя или ссылку на канал" in await ask_channel(repo, messenger, "https://youtu.be/Ab3dE5gH1jK")


def test_channel_query_takes_only_handle_and_channel_id():
    """В Google /channel не ходит: видео и старые адреса по базе не найти (ТЗ, раздел 8)."""
    assert channel_query("@Bike-Example") == ChannelQuery(None, "@bike-example")
    assert channel_query(f"youtube.com/channel/{CHANNEL}") == ChannelQuery(CHANNEL, None)
    assert channel_query("https://www.youtube.com/c/BikeName") is None
    assert channel_query("") is None


async def test_forget_deletes_and_reports_the_count(db):
    repo, messenger = await fill(db), FakeMessenger()
    await on_forget(make_message("/forget", user_id=ADMIN_ID), command("forget", str(USER)), repo=repo,
                    messenger=messenger, texts=TEXTS, brand=BRAND)
    assert messenger.last().endswith("Удалил данные человека 77: аудитов — 1. Копии базы сотрутся сами через 7 дней.")
    async with db.connect() as connection:
        assert (await connection.execute(text("SELECT COUNT(*) FROM users WHERE user_id = 77"))).scalar() == 0


async def test_forget_without_a_number_explains_usage(db):
    messenger = FakeMessenger()
    await on_forget(make_message("/forget", user_id=ADMIN_ID), command("forget", "@someone"), repo=await fill(db),
                    messenger=messenger, texts=TEXTS, brand=BRAND)
    assert "Пришлите Telegram ID человека" in messenger.last()


async def test_only_owner_passes_the_filter(settings):
    assert await IsAdmin()(make_message("/stats", user_id=ADMIN_ID), settings=settings)
    assert not await IsAdmin()(make_message("/stats", user_id=500), settings=settings)
