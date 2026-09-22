"""Async Choice routing; selections are data, never executable actions."""

import asyncio
import math
import os
from time import perf_counter
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .telemetry import DEFAULT_ENDPOINT, Event, FallbackModel, Telemetry, milliseconds, tokens

__version__ = "0.1.0"
# Bounded compatibility allowance for observed API totals such as 0.99.
# This is not a provider guarantee about rounding; preserve the original values.
PROBABILITY_SUM_TOLERANCE = 0.01
_PROBABILITY_SUM_EPSILON = 1e-12
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Reason = Literal[
    "confident",
    "low_confidence",
    "jev_transient_error",
    "invalid_response",
    "jev_request_error",
    "fallback_failed",
    "cancelled",
    "no_fallback",
]


class RouterError(Exception):
    """Base for sanitized router failures."""


class ConfigurationError(RouterError, ValueError):
    pass


class JevRequestError(RouterError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(
            f"Jev request rejected (HTTP {status_code}); check credentials and request configuration"
        )


class FallbackError(RouterError):
    pass


class AbstentionError(RouterError):
    """Jev could not select confidently and no fallback was configured."""

    reason = "no_fallback"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Usage(Record):
    # None means unavailable, not measured zero.
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class RouteRequest(Record):
    state: str | dict[str, JsonValue] | list[JsonValue]
    criteria: dict[str, str] = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_criteria(self):
        if any(not k.strip() or not v.strip() for k, v in self.criteria.items()):
            raise ValueError("Criteria labels and descriptions must be non-empty")
        return self


class FallbackChoice(Record):
    label: str
    usage: Usage = Field(default_factory=Usage)
    model: FallbackModel | None = None


class Decision(Record):
    label: str
    origin: Literal["jev", "fallback"]
    confidence: Probability | None
    reason: Reason
    probabilities: dict[str, Probability] | None = None
    usage: Usage = Field(default_factory=Usage)
    fallback_usage: Usage | None = None


JevErrorCode = Literal[
    "http_error", "timeout", "network_error", "invalid_json", "invalid_usage",
    "invalid_answer", "invalid_labels", "invalid_probability_sum",
]


class DecisionEvent(Record):
    origin: Literal["jev", "fallback", "error", "cancelled"]
    reason: Reason
    jev_ms: float
    fallback_ms: float
    input_tokens: int | None
    output_tokens: int | None
    # Local observer diagnostics only; not added to the telemetry payload.
    jev_reason: Reason | None = None
    jev_error: JevErrorCode | None = None
    jev_http_status: int | None = None
    jev_usage: Usage = Field(default_factory=Usage)
    jev_probability_sum: float | None = None


class Observer(Protocol):
    def on_decision(self, event: DecisionEvent) -> None:
        """Fast, nonblocking metadata-only callback; exceptions are ignored."""


class AsyncFallback(Protocol):
    async def __call__(self, request: RouteRequest) -> FallbackChoice | dict[str, Any]: ...


class _Answer(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["choice"]
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability]


class Router:
    """One Jev attempt, then at most one fallback. No automatic retries.

    An injected client belongs to the caller. Otherwise a short-lived client is
    created per request. Cancellation propagates; all timeouts are cooperative.
    """

    def __init__(
        self,
        *,
        fallback: AsyncFallback | None = None,
        api_key: str | None = None,
        jev_api_key: str | None = None,
        jevcalc_api_key: str | None = None,
        telemetry_endpoint: str = DEFAULT_ENDPOINT,
        telemetry_queue_size: int = 256,
        _telemetry_transport: httpx.MockTransport | None = None,
        client: httpx.AsyncClient | None = None,
        threshold: float = 0.8,
        jev_timeout: float = 10,
        fallback_timeout: float = 30,
        observer: Observer | None = None,
    ):
        if api_key is not None and jev_api_key is not None and api_key != jev_api_key:
            raise ConfigurationError("api_key and jev_api_key conflict")
        key = jev_api_key if jev_api_key is not None else api_key
        key = key if key is not None else os.getenv("TYPESAFE_API_KEY")
        if not key or not key.strip():
            raise ConfigurationError("Set TYPESAFE_API_KEY or pass a non-empty api_key")
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ConfigurationError("threshold must be finite and between 0 and 1")
        if any(not math.isfinite(t) or t <= 0 for t in (jev_timeout, fallback_timeout)):
            raise ConfigurationError("timeouts must be finite and positive")
        self._api_key = key
        self.fallback, self.client, self.threshold = fallback, client, threshold
        self.jev_timeout, self.fallback_timeout, self.observer = jev_timeout, fallback_timeout, observer
        self._closed = False
        # Injected provider transports are commonly synthetic: never report them
        # unless a separate, explicitly isolated test telemetry transport is given.
        fixture = client is not None and not isinstance(client._transport, httpx.AsyncHTTPTransport)
        self._telemetry = None
        if jevcalc_api_key is not None and (not fixture or _telemetry_transport is not None):
            self._telemetry = Telemetry(jevcalc_api_key, telemetry_endpoint, telemetry_queue_size, _telemetry_transport)

    async def flush(self, timeout: float = 1.0) -> bool:
        return True if self._telemetry is None else await self._telemetry.flush(timeout)

    async def aclose(self, timeout: float = 1.0) -> bool:
        self._closed = True
        return True if self._telemetry is None else await self._telemetry.aclose(timeout)

    async def __aenter__(self):
        if self._closed:
            raise ConfigurationError("Router is closed")
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def _post(self, request: RouteRequest) -> httpx.Response:
        kwargs = dict(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self.jev_timeout,
            follow_redirects=False,
            json={
                "state": request.state,
                "model": "jev-latest",
                "questions": {
                    "route": {
                        "type": "choice",
                        "instructions": request.instructions,
                        "criteria": request.criteria,
                    }
                },
            },
        )
        url = "https://api.typesafe.ai/v1/systemone"
        if self.client is not None:
            return await self.client.post(url, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.post(url, **kwargs)

    async def route(
        self,
        state: str | dict | list,
        criteria: dict[str, str],
        *,
        instructions: str = "Select the best route",
    ) -> Decision:
        if self._closed:
            raise ConfigurationError("Router is closed")
        request = RouteRequest(state=state, criteria=criteria, instructions=instructions)
        allowed = frozenset(request.criteria)
        start, jev_ms, fallback_ms = perf_counter(), 0.0, 0.0
        usage, fallback_usage = Usage(), Usage()
        origin, reason = "error", "invalid_response"
        status_code, confidence, fallback_model = None, None, None
        fallback_started = False
        jev_reason, jev_error, probability_sum = None, None, None
        try:
            try:
                async with asyncio.timeout(self.jev_timeout):
                    response = await self._post(request)
                status_code = response.status_code
                if response.status_code == 429 or response.status_code >= 500:
                    reason, jev_error = "jev_transient_error", "http_error"
                elif not 200 <= response.status_code < 300:
                    reason, jev_error = "jev_request_error", "http_error"
                    raise JevRequestError(response.status_code)
                else:
                    try:
                        jev_error = "invalid_json"
                        data = response.json()
                        jev_error = "invalid_usage"
                        usage = Usage.model_validate(data.get("usage", {})) if isinstance(data, dict) else Usage()
                        jev_error = "invalid_answer"
                        answer = _Answer.model_validate(data["answers"]["route"])
                        jev_error = "invalid_labels"
                        if answer.choice not in allowed or set(answer.probabilities) != allowed:
                            raise ValueError("Unknown labels or incomplete distribution")
                        probability_sum = sum(answer.probabilities.values())
                        jev_error = "invalid_probability_sum"
                        if abs(probability_sum - 1.0) > PROBABILITY_SUM_TOLERANCE + _PROBABILITY_SUM_EPSILON:
                            raise ValueError("Probability sum outside compatibility tolerance")
                        jev_error = None
                        confidence = answer.confidence
                        if answer.confidence >= self.threshold:
                            origin, reason = "jev", "confident"
                            return Decision(
                                label=answer.choice,
                                origin=origin,
                                confidence=answer.confidence,
                                reason=reason,
                                probabilities=answer.probabilities,
                                usage=usage,
                            )
                        reason = "low_confidence"
                    except (ValueError, KeyError, TypeError):
                        reason = "invalid_response"
            except (httpx.TimeoutException, TimeoutError):
                reason, jev_error = "jev_transient_error", "timeout"
            except httpx.RequestError:
                reason, jev_error = "jev_transient_error", "network_error"
            finally:
                jev_reason = reason
                jev_ms = (perf_counter() - start) * 1000
            if self.fallback is None:
                reason = "no_fallback"
                raise AbstentionError("No confident selection and no fallback configured")
            fallback_start = perf_counter()
            fallback_started = True
            try:
                async with asyncio.timeout(self.fallback_timeout):
                    raw = await self.fallback(request.model_copy(deep=True))
                choice = FallbackChoice.model_validate(raw)
                if choice.label not in allowed:
                    raise ValueError("Fallback label is not an allowed route")
                fallback_usage = choice.usage
                fallback_model = choice.model
            except Exception:
                reason = "fallback_failed"
                raise FallbackError("Fallback failed, timed out, or returned an invalid selection") from None
            finally:
                fallback_ms = (perf_counter() - fallback_start) * 1000
            origin = "fallback"
            return Decision(
                label=choice.label,
                origin=origin,
                confidence=None,
                reason=reason,
                usage=usage,
                fallback_usage=fallback_usage,
            )
        except asyncio.CancelledError:
            origin, reason = "cancelled", "cancelled"
            raise
        finally:
            if self._telemetry is not None:
                try:
                    self._telemetry.emit(Event(
                        input_tokens=tokens(usage.input_tokens),
                        duration_ms=milliseconds((perf_counter() - start) * 1000),
                        jev_duration_ms=milliseconds(jev_ms),
                        fallback_duration_ms=milliseconds(fallback_ms) if fallback_started else None,
                        status_code=status_code, confidence=confidence,
                        origin=origin, reason=reason, fallback_model=fallback_model,
                        fallback_input_tokens=tokens(fallback_usage.input_tokens),
                        fallback_output_tokens=tokens(fallback_usage.output_tokens),
                    ))
                except Exception:
                    self._telemetry.dropped += 1
            if self.observer is not None:

                def total(a, b):
                    return None if a is None and b is None else (a or 0) + (b or 0)

                event = DecisionEvent(
                    origin=origin,
                    reason=reason,
                    jev_ms=jev_ms,
                    fallback_ms=fallback_ms,
                    input_tokens=total(usage.input_tokens, fallback_usage.input_tokens),
                    output_tokens=total(usage.output_tokens, fallback_usage.output_tokens),
                    jev_reason=jev_reason,
                    jev_error=jev_error,
                    jev_http_status=status_code,
                    jev_usage=usage,
                    jev_probability_sum=probability_sum,
                )
                try:
                    self.observer.on_decision(event)
                except Exception:
                    pass
