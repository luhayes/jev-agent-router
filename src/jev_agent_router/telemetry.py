"""Opt-in, memory-only v1 telemetry. Never accepts request/response content."""

import asyncio

from datetime import datetime, timezone
import json
import math
import random
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ENDPOINT = "https://jevcalc.com/api/v1/events"
FallbackModel = Literal["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "other"]
MODELS = frozenset(("gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"))


def safe_model(model: str) -> FallbackModel:
    return model if model in MODELS else "other"


def tokens(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def milliseconds(value):
    return min(300000.0, max(0.0, value)) if math.isfinite(value) else 300000.0


class Event(BaseModel):
    """Closed wire allowlist. No arbitrary strings, tags or provider objects."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    input_tokens: int | None = Field(ge=0, le=1_000_000_000)
    questions: Literal[1] = 1
    duration_ms: float = Field(ge=0, le=300000, allow_inf_nan=False)
    jev_duration_ms: float = Field(ge=0, le=300000, allow_inf_nan=False)
    fallback_duration_ms: float | None = Field(ge=0, le=300000, allow_inf_nan=False)
    status_code: int | None = Field(ge=100, le=599)
    confidence: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    origin: Literal["jev", "fallback", "error", "cancelled"]
    reason: Literal["confident", "low_confidence", "jev_transient_error", "invalid_response", "jev_request_error", "fallback_failed", "cancelled", "no_fallback"]
    fallback_model: FallbackModel | None
    fallback_input_tokens: int | None = Field(ge=0, le=1_000_000_000)
    fallback_output_tokens: int | None = Field(ge=0, le=1_000_000_000)


class Telemetry:
    def __init__(self, key, endpoint=DEFAULT_ENDPOINT, queue_size=256, transport=None):
        try:
            url = httpx.URL(endpoint)
            local = url.host in {"localhost", "127.0.0.1", "::1"}
            valid = (url.scheme == "https" or (url.scheme == "http" and local)) and url.host
            if not valid or url.userinfo or url.query or url.fragment or url.path != "/api/v1/events":
                raise ValueError
        except Exception:
            raise ValueError("Telemetry endpoint must be HTTPS (or explicit loopback HTTP), without credentials/query/fragment, at /api/v1/events") from None
        if type(queue_size) is not int or not 1 <= queue_size <= 10000:
            raise ValueError("telemetry_queue_size must be an integer between 1 and 10000")
        if not isinstance(key, str) or not key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("jevcalc_api_key must be a non-empty ASCII token")
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Test telemetry transport must be an isolated MockTransport")
        self._key, self._endpoint, self._transport = key, str(url), transport
        self._queue = asyncio.Queue(maxsize=queue_size)
        self._task = self._client = None
        self._closed = False
        self._stopping = False
        self.dropped = self.sent = self.failed = 0

    def emit(self, event: Event):
        if self._closed:
            self.dropped += 1
            return
        try:
            loop = asyncio.get_running_loop()
            self._queue.put_nowait(event.model_dump())
        except (RuntimeError, asyncio.QueueFull):
            self.dropped += 1
            return
        if self._task is None:
            self._task = loop.create_task(self._worker(), name="jevcalc-telemetry")

    async def _send(self, batch):
        body = json.dumps({"schema_version": 1, "events": batch}, allow_nan=False, separators=(",", ":")).encode()
        if len(body) > 128 * 1024:
            return False
        for attempt in range(3):
            try:
                async with asyncio.timeout(2):
                    response = await self._client.post(self._endpoint, content=body, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}, follow_redirects=False)
                if response.status_code == 202:
                    return True
                if response.status_code != 429 and not 500 <= response.status_code <= 599:
                    return False
            except (httpx.RequestError, TimeoutError):
                pass
            if attempt < 2:
                await asyncio.sleep(random.uniform(0.025, 0.075) * (2 ** attempt))
        return False

    async def _worker(self):
        try:
            async with httpx.AsyncClient(transport=self._transport, trust_env=False, follow_redirects=False, timeout=2) as client:
                self._client = client
                while not self._stopping:
                    batch = [await self._queue.get()]
                    while len(batch) < 100 and not self._queue.empty():
                        batch.append(self._queue.get_nowait())
                    try:
                        if await self._send(batch):
                            self.sent += len(batch)
                        else:
                            self.failed += len(batch)
                    except asyncio.CancelledError:
                        self.dropped += len(batch)
                        raise
                    except Exception:
                        self.failed += len(batch)
                    finally:
                        for _ in batch:
                            self._queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Transport setup failure must never become an unhandled task error.
            self._closed = True
            self._discard()

    def _discard(self):
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
            self.dropped += 1

    async def flush(self, timeout=1.0):
        """True = queue drained (including dropped/failed), NOT upload success."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("flush timeout must be finite and nonnegative")
        if self._task is None or self._queue._unfinished_tasks == 0:
            return True
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
            return True
        except TimeoutError:
            return False

    async def aclose(self, timeout=1.0):
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("close timeout must be finite and nonnegative")
        deadline = asyncio.get_running_loop().time() + timeout
        self._closed = True
        try:
            # Reserve a small part of the caller's bound for cancellation/cleanup.
            return await self.flush(timeout * 0.9)
        finally:
            self._stopping = True
            if self._task is not None:
                self._task.cancel()
                # wait(), unlike wait_for(), cannot hang awaiting cancellation
                # acknowledgement from an uncooperative injected transport.
                await asyncio.wait({self._task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
            self._discard()
