"""Клиент YouTube Data API v3 (ТЗ, 5.1, 5.3, С1–С2).

- Адрес — только постоянная часть и имя метода; присланное человеком попадает только в параметры (С1).
- Ключ — в заголовке X-goog-api-key, не в адресе: адрес попадает в тексты ошибок (Сек6).
- Каждый запрос, даже с ошибкой, стоит единицу квоты: счёт — до отправки (5.1).
- Переадресации не проходим; прокси из окружения не берёт сама сессия — её создают с trust_env=False (С2).
- В журнал — номер аудита, метод, HTTP-статус и reason; адреса, параметров и текста ответа там нет (Сек7).
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
from loguru import logger

from bot.channel_audit.quota import QUOTA, QuotaGate
from bot.core.clock import Clock

BASE_URL = "https://www.googleapis.com/youtube/v3/"
KEY_HEADER = "X-goog-api-key"
REQUEST_TIMEOUT_SECONDS = 10
MIN_TIMEOUT_SECONDS = 1
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_ATTEMPTS = 2
RETRY_MIN_REMAINING_SECONDS = 10
RATE_LIMIT_PAUSE_SECONDS = 2
UNITS_PER_REQUEST = 1
HTTP_OK = 200
TOO_MANY_REQUESTS = 429
FIRST_CLIENT_ERROR = 400
FIRST_SERVER_ERROR = 500
NO_REASON = "—"
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
KEY_REASONS = frozenset({"keyInvalid", "keyExpired", "forbidden", "accessNotConfigured", "ipRefererBlocked"})
KEY = "key"
RATE = "rate"
SHAPE = "shape"
TOO_LARGE = "too_large"


class YouTubeError(Exception):
    """Общий предок ошибок клиента."""


class NotFound(YouTubeError):
    """Google ответил на присланное «нет такого» (4xx) — попытка списывается (ТЗ, Л5)."""


class QuotaExhausted(YouTubeError):
    """Квота Google или свой потолок единиц — до полуночи по тихоокеанскому времени (ТЗ, Л9)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ServiceDown(YouTubeError):
    """Сбой не по вине присланного: ключ, частота, 5xx, сеть, ответ не той формы. reason — в журнал и владельцу."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Retryable(Exception):
    def __init__(self, reason: str, pause: float = 0):
        super().__init__(reason)
        self.reason = reason
        self.pause = pause


@dataclass
class Meter:
    """Сколько единиц потратил один аудит (ТЗ, раздел 12, api_units); номер аудита — для журнала."""

    audit_id: int | None = None
    units: int = 0


class YouTubeClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str, clock: Clock, quota: QuotaGate, *,
                 base_url: str = BASE_URL, request_timeout: float = REQUEST_TIMEOUT_SECONDS,
                 max_bytes: int = MAX_RESPONSE_BYTES):
        self._session = session
        self._key = api_key
        self._clock = clock
        self._quota = quota
        self._base_url = base_url
        self._request_timeout = request_timeout
        self._max_bytes = max_bytes

    async def call(self, method: str, params: dict[str, str], deadline: float, meter: Meter) -> dict[str, Any]:
        """Ответ Google или исключение. deadline — момент clock.monotonic(), к которому аудит кончается."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await self._once(method, params, deadline, meter)
            except _Retryable as error:
                if attempt == MAX_ATTEMPTS or deadline - self._clock.monotonic() <= RETRY_MIN_REMAINING_SECONDS:
                    raise ServiceDown(error.reason) from None
                await asyncio.sleep(error.pause)
        raise AssertionError("недостижимо")

    async def _once(self, method: str, params: dict[str, str], deadline: float, meter: Meter) -> dict[str, Any]:
        blocked = self._quota.block_reason()
        if blocked:
            raise QuotaExhausted(blocked)
        meter.units += UNITS_PER_REQUEST
        await self._quota.spend(UNITS_PER_REQUEST)
        status, body = await self._request(method, params, deadline)
        payload = _json_or_none(body)
        logger.info("аудит {}: YouTube {} — HTTP {}, reason {}", meter.audit_id, method, status, reason_of(payload))
        return await self._interpret(status, payload)

    async def _request(self, method: str, params: dict[str, str], deadline: float) -> tuple[int, bytes]:
        seconds = min(self._request_timeout, max(MIN_TIMEOUT_SECONDS, deadline - self._clock.monotonic()))
        request = self._session.get(self._base_url + method, params=params, headers={KEY_HEADER: self._key},
                                    timeout=aiohttp.ClientTimeout(total=seconds), allow_redirects=False)
        try:
            async with request as response:
                return response.status, await self._read(response)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise _Retryable(f"network: {type(error).__name__}") from None

    async def _read(self, response: aiohttp.ClientResponse) -> bytes:
        body = bytearray()
        async for chunk in response.content.iter_chunked(READ_CHUNK_BYTES):
            body.extend(chunk)
            if len(body) > self._max_bytes:
                raise ServiceDown(TOO_LARGE)
        return bytes(body)

    async def _interpret(self, status: int, payload: dict[str, Any] | None) -> dict[str, Any]:
        reason = reason_of(payload)
        if status == HTTP_OK and payload is not None:
            return payload
        if reason in QUOTA_REASONS:
            await self._quota.exhaust()
            raise QuotaExhausted(QUOTA)
        if reason in RATE_REASONS or status == TOO_MANY_REQUESTS:
            raise _Retryable(RATE, RATE_LIMIT_PAUSE_SECONDS)
        if reason in KEY_REASONS:
            raise ServiceDown(KEY)
        if status >= FIRST_SERVER_ERROR:
            raise _Retryable(f"http {status}")
        if status >= FIRST_CLIENT_ERROR:
            raise NotFound(reason)
        raise ServiceDown(SHAPE)


def _json_or_none(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def reason_of(payload: dict[str, Any] | None) -> str:
    error = (payload or {}).get("error")
    errors = error.get("errors") if isinstance(error, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    return str(first.get("reason") or NO_REASON)
