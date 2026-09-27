from bot.channel_audit.kv import Kv


async def test_set_get_overwrite_delete(db):
    kv = Kv(db)
    assert await kv.get("banner:ru") is None
    await kv.set("banner:ru", "first")
    await kv.set("banner:ru", "second")
    assert await kv.get("banner:ru") == "second"
    await kv.delete("banner:ru")
    assert await kv.get("banner:ru") is None
