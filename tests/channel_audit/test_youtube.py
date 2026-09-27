import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from loguru import logger

from bot.channel_audit import youtube
from bot.channel_audit.kv import Kv
from bot.channel_audit.quota import CEILING, QuotaGate
from bot.channel_audit.youtube import KEY, KEY_HEADER, Meter, NotFound, QuotaExhausted, ServiceDown, YouTubeClient
from tests.fakes import FakeClock, fake_google_key

OK_BODY = {"items": [{"id": "UCabcdefghijABCDEFGHIJ12"}]}


def google_error(status: int, reason: str) -> dict:
    return {"error": {"code": status, "message": "…", "errors": [{"reason": reason}]}}


def google_error_with_detail(status: int, reason: str, detail_reason: str) -> dict:
    return {"error": {"code": status, "message": "…", "errors": [{"reason": reason}],
                      "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": detail_reason,
                                  "domain": "googleapis.com"}]}}


class FakeGoogle:
    """Отвечает заготовками по очереди и запоминает запросы."""

    def __init__(self, *answers: tuple[int, dict | str], delay: float = 0.0):
        self.answers = list(answers)
        self.requests: list[web.Request] = []
        self.delay = delay

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(request)
        await asyncio.sleep(self.delay)
        status, body = self.answers.pop(0)
        text = body if isinstance(body, str) else json.dumps(body)
        return web.Response(status=status, text=text, content_type="application/json")


@pytest.fixture
async def youtube_client(db):
    opened = []

    async def make(fake: FakeGoogle, ceiling: int = 8000, **options):
        app = web.Application()
        app.router.add_get("/youtube/v3/{method}", fake.handle)
        server, session = TestServer(app), aiohttp.ClientSession(trust_env=False)
        opened.append((server, session))
        await server.start_server()
        clock = FakeClock()
        gate = QuotaGate(Kv(db), clock, ceiling)
        base_url = str(server.make_url("/youtube/v3/"))
        return YouTubeClient(session, fake_google_key(), clock, gate, base_url=base_url, **options), gate, clock

    yield make
    for server, session in opened:
        await session.close()
        await server.close()


async def call(client, clock, params=None, seconds_left=30, meter=None):
    params = params or {"part": "id", "forHandle": "@bike_rental_example"}
    return await client.call("channels", params, clock.monotonic() + seconds_left, meter or Meter(1))


async def test_key_goes_in_the_header_and_each_request_costs_a_unit(youtube_client):
    fake = FakeGoogle((200, OK_BODY))
    client, gate, clock = await youtube_client(fake)
    meter = Meter(7)
    assert await call(client, clock, meter=meter) == OK_BODY
    request = fake.requests[0]
    assert request.headers[KEY_HEADER] == fake_google_key()
    assert "key" not in request.query
    assert request.path == "/youtube/v3/channels"
    assert (meter.units, gate.units_today()) == (1, 1)


async def test_what_the_person_sent_goes_only_into_parameters(youtube_client):
    fake = FakeGoogle((200, OK_BODY))
    client, _, clock = await youtube_client(fake)
    await call(client, clock, params={"part": "id", "forHandle": "https://evil.example/x"})
    assert fake.requests[0].path == "/youtube/v3/channels"
    assert fake.requests[0].query["forHandle"] == "https://evil.example/x"


@pytest.mark.parametrize(("status", "reason"), [(404, "channelNotFound"), (400, "invalidParameter")])
async def test_client_errors_mean_not_found(youtube_client, status, reason):
    client, _, clock = await youtube_client(FakeGoogle((status, google_error(status, reason))))
    with pytest.raises(NotFound):
        await call(client, clock)


async def test_quota_exceeded_blocks_further_calls_without_requests(youtube_client):
    fake = FakeGoogle((403, google_error(403, "quotaExceeded")))
    client, _, clock = await youtube_client(fake)
    for _ in range(2):
        with pytest.raises(QuotaExhausted):
            await call(client, clock)
    assert len(fake.requests) == 1


async def test_own_ceiling_blocks_before_the_request(youtube_client):
    fake = FakeGoogle((200, OK_BODY))
    client, _, clock = await youtube_client(fake, ceiling=1)
    await call(client, clock)
    with pytest.raises(QuotaExhausted) as blocked:
        await call(client, clock)
    assert blocked.value.reason == CEILING
    assert len(fake.requests) == 1


async def test_rate_limit_pauses_and_retries_once(youtube_client, monkeypatch):
    monkeypatch.setattr(youtube, "RATE_LIMIT_PAUSE_SECONDS", 0)
    fake = FakeGoogle((403, google_error(403, "rateLimitExceeded")), (200, OK_BODY))
    client, gate, clock = await youtube_client(fake)
    assert await call(client, clock) == OK_BODY
    assert (len(fake.requests), gate.units_today()) == (2, 2)


async def test_rejected_key_is_service_down_without_retry(youtube_client):
    fake = FakeGoogle((400, google_error(400, "keyInvalid")))
    client, _, clock = await youtube_client(fake)
    with pytest.raises(ServiceDown) as down:
        await call(client, clock)
    assert (down.value.reason, len(fake.requests)) == ("key", 1)


async def test_bad_request_with_key_invalid_detail_is_service_down_key(youtube_client):
    """Ключ мёртв или опечатан — Google теперь кладёт причину в error.details, а errors[0].reason — badRequest."""
    fake = FakeGoogle((400, google_error_with_detail(400, "badRequest", "API_KEY_INVALID")))
    client, _, clock = await youtube_client(fake)
    with pytest.raises(ServiceDown) as down:
        await call(client, clock)
    assert down.value.reason == KEY


async def test_plain_bad_request_without_key_detail_is_still_not_found(youtube_client):
    fake = FakeGoogle((400, google_error(400, "badRequest")))
    client, _, clock = await youtube_client(fake)
    with pytest.raises(NotFound):
        await call(client, clock)


async def test_server_error_is_retried_once(youtube_client):
    fake = FakeGoogle((503, "Service Unavailable"), (200, OK_BODY))
    client, _, clock = await youtube_client(fake)
    assert await call(client, clock) == OK_BODY
    assert len(fake.requests) == 2


async def test_two_server_errors_give_up(youtube_client):
    client, _, clock = await youtube_client(FakeGoogle((503, "x"), (503, "x")))
    with pytest.raises(ServiceDown, match="http 503"):
        await call(client, clock)


async def test_no_retry_when_ten_seconds_or_less_are_left(youtube_client):
    fake = FakeGoogle((503, "x"), (200, OK_BODY))
    client, _, clock = await youtube_client(fake)
    with pytest.raises(ServiceDown):
        await call(client, clock, seconds_left=10)
    assert len(fake.requests) == 1


async def test_slow_answer_is_retried_then_service_down(youtube_client):
    fake = FakeGoogle((200, OK_BODY), (200, OK_BODY), delay=0.5)
    client, _, clock = await youtube_client(fake, request_timeout=0.1)
    with pytest.raises(ServiceDown, match="network"):
        await call(client, clock)


async def test_network_failure_is_logged_with_audit_id_method_and_error_type(youtube_client):
    """Сетевой сбой не проходит молча (F8): в журнал — номер аудита, метод и тип ошибки, без адреса и текста."""
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        fake = FakeGoogle((200, OK_BODY), (200, OK_BODY), delay=0.5)
        client, _, clock = await youtube_client(fake, request_timeout=0.1)
        with pytest.raises(ServiceDown):
            await call(client, clock, meter=Meter(42))
    finally:
        logger.remove(sink)
    text = "".join(lines)
    assert "42" in text and "channels" in text and "TimeoutError" in text


async def test_huge_answer_is_refused(youtube_client):
    client, _, clock = await youtube_client(FakeGoogle((200, OK_BODY)), max_bytes=10)
    with pytest.raises(ServiceDown, match="too_large"):
        await call(client, clock)


async def test_answer_that_is_not_json_is_service_down(youtube_client):
    client, _, clock = await youtube_client(FakeGoogle((200, "<html>")))
    with pytest.raises(ServiceDown, match="shape"):
        await call(client, clock)


async def test_log_has_method_status_and_reason_but_not_parameters(youtube_client):
    """ТЗ, Сек7: журнал Docker ротируется по размеру, данные YouTube жили бы в нём месяцами."""
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        client, _, clock = await youtube_client(FakeGoogle((404, google_error(404, "channelNotFound"))))
        with pytest.raises(NotFound):
            await call(client, clock, params={"part": "id", "forHandle": "@secret_handle_example"})
    finally:
        logger.remove(sink)
    text = "".join(lines)
    assert "channels" in text and "404" in text and "channelNotFound" in text
    assert "secret_handle_example" not in text
