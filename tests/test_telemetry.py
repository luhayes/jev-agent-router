import asyncio
import json
from typing import get_args

import httpx
import pytest

from jev_agent_router import Router, RouterError


def response(confidence=0.9):
    return httpx.Response(
        200,
        json={
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "private-label",
                    "confidence": confidence,
                    "probabilities": {"private-label": 0.9, "private-other": 0.1},
                }
            },
            "usage": {"input_tokens": 12},
        },
    )


async def route(router):
    return await router.route(
        "private-state",
        {"private-label": "private-criteria", "private-other": "other"},
        instructions="private-instructions",
    )


async def test_key_alias_no_fallback_abstains():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response(0.2))) as client:
        router = Router(jev_api_key="provider-secret", client=client)
        with pytest.raises(RouterError) as caught:
            await route(router)
        assert type(caught.value).__name__ == "AbstentionError"
        assert caught.value.reason == "no_fallback"


def test_conflicting_aliases_rejected():
    with pytest.raises(ValueError, match="conflict"):
        Router(api_key="a", jev_api_key="b")


FIELDS = set(
    "event_id occurred_at input_tokens questions duration_ms jev_duration_ms fallback_duration_ms status_code confidence origin reason fallback_model fallback_input_tokens fallback_output_tokens".split()
)


def test_no_key_has_no_telemetry_even_with_environment(monkeypatch):
    monkeypatch.setenv("JEVCALC_API_KEY", "not-opted-in")
    router = Router(api_key="provider-secret")
    assert router._telemetry is None


def test_enabled_construction_outside_loop_is_lazy():
    router = Router(api_key="provider-secret", jevcalc_api_key="analytics-secret")
    assert router._telemetry._task is None
    assert router._telemetry._client is None


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/api/v1/events",
        "https://user:pass@example.com/api/v1/events",
        "https://example.com/api/v1/events?secret=x",
        "https://example.com/api/v1/events#secret",
    ],
)
def test_unsafe_endpoint_rejected(endpoint):
    with pytest.raises(ValueError):
        Router(api_key="provider-secret", jevcalc_api_key="analytics-secret", telemetry_endpoint=endpoint)


async def test_exact_private_event_and_context_flush():
    outgoing = []

    def collect(request):
        outgoing.append(request)
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        async with Router(
            api_key="provider-secret",
            client=client,
            jevcalc_api_key="analytics-secret",
            _telemetry_transport=httpx.MockTransport(collect),
        ) as router:
            await route(router)
    assert len(outgoing) == 1
    sent = outgoing[0]
    assert str(sent.url) == "https://jevcalc.com/api/v1/events"
    assert sent.headers["authorization"] == "Bearer analytics-secret"
    wire = str(dict(sent.headers)) + sent.content.decode()
    for secret in [
        "private-state",
        "private-label",
        "private-other",
        "private-criteria",
        "private-instructions",
        "provider-secret",
    ]:
        assert secret not in wire
    body = json.loads(sent.content)
    assert set(body) == {"schema_version", "events"}
    assert body["schema_version"] == 1
    event = body["events"][0]
    assert set(event) == FIELDS
    assert event["questions"] == 1
    assert event["input_tokens"] == 12
    assert event["confidence"] == 0.9
    assert event["status_code"] == 200
    assert event["fallback_duration_ms"] is None
    assert event["origin"] == "jev"
    assert router._telemetry._task.done()


async def test_fixture_never_reports_without_isolated_injection():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        async with Router(
            api_key="provider-secret", client=client, jevcalc_api_key="analytics-secret"
        ) as router:
            await route(router)
            assert router._telemetry is None


async def test_bounded_queue_flush_and_close_never_stall_routing():
    entered = asyncio.Event()

    async def hang(request):
        entered.set()
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        router = Router(
            api_key="provider-secret",
            client=client,
            jevcalc_api_key="analytics-secret",
            telemetry_queue_size=2,
            _telemetry_transport=httpx.MockTransport(hang),
        )
        await route(router)
        await entered.wait()
        async with asyncio.timeout(0.5):
            for _ in range(10):
                await route(router)
        assert router._telemetry.dropped >= 8
        assert not await router.flush(timeout=0.01)
        async with asyncio.timeout(0.5):
            await router.aclose(timeout=0.01)
        assert router._telemetry._task.done()
        await router.aclose()


@pytest.mark.parametrize("status,expected", [(503, 3), (429, 3), (401, 1), (403, 1), (307, 1)])
async def test_retry_bounded_and_no_redirect(status, expected):
    sent = []

    def fail(request):
        sent.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.example/steal"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        async with Router(
            api_key="provider-secret",
            client=client,
            jevcalc_api_key="analytics-secret",
            _telemetry_transport=httpx.MockTransport(fail),
        ) as router:
            await route(router)
            assert await router.flush(timeout=2)
    assert len(sent) == expected
    assert all(r.url.host == "jevcalc.com" for r in sent)
    assert all(r.content == sent[0].content for r in sent)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("private-custom-model", "other"),
        # Retired but still in the enum so historical rows keep pricing.
        ("gpt-4o", "gpt-4o"),
        # Current models must pass through rather than collapse to "other";
        # "other" prices as unknown and drops the event from savings entirely.
        ("gpt-5-6-terra", "gpt-5-6-terra"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
        ("gemini-2-5-flash-lite", "gemini-2-5-flash-lite"),
    ],
)
async def test_fallback_confidence_usage_model_privacy(model, expected):
    from jev_agent_router.openai import OpenAIJSONFallback

    sent = []

    def collect(request):
        sent.append(request)
        return httpx.Response(202)

    def completion(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps({"label": "private-label"})}}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3},
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response(0.2))) as jev,
        httpx.AsyncClient(transport=httpx.MockTransport(completion)) as openai,
    ):
        fallback = OpenAIJSONFallback(model=model, api_key="openai-secret", client=openai)
        async with Router(
            api_key="provider-secret",
            client=jev,
            fallback=fallback,
            jevcalc_api_key="analytics-secret",
            _telemetry_transport=httpx.MockTransport(collect),
        ) as router:
            result = await route(router)
            # Decision confidence still describes the chosen label (not fallback confidence).
            assert result.confidence is None
    event = json.loads(sent[0].content)["events"][0]
    assert event["confidence"] == 0.2
    assert event["fallback_model"] == expected
    assert event["fallback_input_tokens"] == 20
    assert event["fallback_output_tokens"] == 3
    assert event["input_tokens"] == 12
    assert event["origin"] == "fallback"
    assert event["reason"] == "low_confidence"
    assert event["status_code"] == 200
    wire = str(dict(sent[0].headers)) + sent[0].content.decode()
    assert "private-" not in wire
    assert "openai-secret" not in wire
    assert "provider-secret" not in wire


@pytest.mark.parametrize(
    "mode,status,reason,origin",
    [
        ("timeout", None, "no_fallback", "error"),
        ("auth", 401, "jev_request_error", "error"),
        ("invalid", 200, "no_fallback", "error"),
        ("fallback", 200, "fallback_failed", "error"),
        ("cancel", None, "cancelled", "cancelled"),
    ],
)
async def test_failure_metadata_never_contains_provider_errors(mode, status, reason, origin):
    sent = []

    def provider(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private-provider-error provider-secret openai-secret")
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode == "auth":
            return httpx.Response(401, text="private-provider-error provider-secret")
        if mode == "invalid":
            return httpx.Response(200, json={"private-provider-error": "openai-secret"})
        return response(0.2)

    async def fail(request):
        raise ValueError("private-provider-error openai-secret")

    def collect(request):
        sent.append(request)
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        async with Router(
            api_key="provider-secret",
            client=client,
            fallback=fail if mode == "fallback" else None,
            jevcalc_api_key="analytics-secret",
            _telemetry_transport=httpx.MockTransport(collect),
        ) as router:
            with pytest.raises((RouterError, asyncio.CancelledError)):
                await route(router)
    event = json.loads(sent[0].content)["events"][0]
    assert event["status_code"] == status
    assert event["reason"] == reason
    assert event["origin"] == origin
    wire = str(dict(sent[0].headers)) + sent[0].content.decode()
    assert not any(s in wire for s in ["private-", "provider-secret", "openai-secret"])


async def test_bridge_explicit_environment_propagation_and_close(monkeypatch):
    from integrations.bridge import router_context

    monkeypatch.setenv("TYPESAFE_API_KEY", "provider-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("JEV_FALLBACK_MODEL", "gpt-4o")
    monkeypatch.setenv("JEVCALC_API_KEY", "analytics-secret")
    async with router_context() as router:
        assert router._telemetry is not None
        assert router._telemetry._task is None
    assert router._closed
    async with router_context(test_only=True) as offline:
        assert offline._telemetry is None
        await route(offline)


async def test_close_bound_even_if_transport_delays_cancellation():
    started, release = asyncio.Event(), asyncio.Event()

    async def stubborn(request):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        router = Router(
            api_key="provider-secret",
            client=client,
            jevcalc_api_key="analytics-secret",
            _telemetry_transport=httpx.MockTransport(stubborn),
        )
        await route(router)
        await started.wait()
        closing = asyncio.create_task(router.aclose(timeout=0.02))
        done, _ = await asyncio.wait({closing}, timeout=0.15)
        bounded = closing in done
        release.set()
        await closing
        # Allow cooperative transport cleanup after a hostile delayed cancellation.
        await asyncio.sleep(0.01)
        if not router._telemetry._task.done():
            router._telemetry._task.cancel()
        assert bounded


async def test_batch_event_limit_local_endpoint_and_unknown_usage():
    from uuid import UUID
    from datetime import datetime, timezone

    requests = []

    def collect(request):
        requests.append(request)
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response())) as client:
        async with Router(
            api_key="provider-secret",
            client=client,
            jevcalc_api_key="analytics-secret",
            telemetry_endpoint="http://localhost:3210/api/v1/events",
            _telemetry_transport=httpx.MockTransport(collect),
        ) as router:
            for _ in range(205):
                await route(router)
    events = [e for r in requests for e in json.loads(r.content)["events"]]
    assert len(events) == 205
    assert len({e["event_id"] for e in events}) == 205
    assert all(
        1 <= len(json.loads(r.content)["events"]) <= 100 and len(r.content) <= 128 * 1024 for r in requests
    )
    for e in events:
        assert str(UUID(e["event_id"])) == e["event_id"]
        assert datetime.fromisoformat(e["occurred_at"]).tzinfo == timezone.utc


def test_fallback_model_enum_matches_shared_contract():
    """The enum is one contract with jevcalc-api's rates table and the console.

    Kept as an explicit list rather than derived, so that widening the enum in
    one repository without the others fails here instead of silently shipping
    events the API rejects, or models that price as unknown.
    """
    from jev_agent_router.telemetry import MODELS, FallbackModel

    assert set(get_args(FallbackModel)) == {
        "gpt-6-astra",
        "gpt-5-6-terra",
        "gpt-5-6-luna",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "gemini-3-8-flash",
        "gemini-2-5-flash-lite",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "other",
    }
    # "other" is the sentinel for an unlisted model, never a reportable one.
    assert "other" not in MODELS
    assert MODELS == set(get_args(FallbackModel)) - {"other"}
