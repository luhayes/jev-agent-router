import asyncio
import httpx
import pytest
import jev_agent_router as api

CRITERIA = {"billing": "Payments", "technical": "Bugs"}


def payload(**overrides):
    answer = dict(
        type="choice", choice="billing", confidence=0.81, probabilities={"billing": 0.88, "technical": 0.12}
    )
    answer.update(overrides)
    return {"answers": {"route": answer}}


async def fallback(request):
    assert request.criteria == CRITERIA
    return {"label": "technical"}


async def run(data=None, status=200, fallback_fn=fallback, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=data))
    ) as client:
        return await api.Router(api_key="secret", client=client, fallback=fallback_fn, **kwargs).route(
            "private", CRITERIA
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        {"confidence": 0.79},
        {"confidence": 1.1},
        {"confidence": -1},
        {"confidence": "0.9"},
        {"choice": "delete_everything"},
        {"type": "score"},
        {"probabilities": {"billing": 1}},
        {"probabilities": {"billing": 0.9, "technical": 0.9}},
        {"probabilities": {"billing": 1.1, "technical": -0.1}},
        {"probabilities": {"billing": 0.8, "technical": 0.1, "extra": 0.1}},
    ],
)
async def test_invalid_or_uncertain_answer_falls_back(answer):
    result = await run(payload(**answer))
    assert result.origin == "fallback"
    assert result.label == "technical"
    assert result.confidence is None


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {}, {"answers": {"route": {}}}])
async def test_unknown_response_fallback(data):
    assert (await run(data)).origin == "fallback"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 529])
async def test_transient_falls_back(status):
    assert (await run({}, status)).reason == "jev_transient_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 400, 422])
async def test_terminal_http_failure_no_fallback_or_retry(status):
    calls = []

    async def forbidden(request):
        pytest.fail("terminal errors must not invoke fallback")

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private server error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(api.JevRequestError) as exc:
            await api.Router(api_key="secret", client=client, fallback=forbidden).route("private", CRITERIA)
    assert len(calls) == 1
    assert "private" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [{"label": "unknown"}, {"label": "billing", "confidence": 0.99}, "billing", None]
)
async def test_invalid_fallback_typed_failure(value):
    async def invalid(request):
        return value

    with pytest.raises(api.FallbackError):
        await run(payload(confidence=0.1), fallback_fn=invalid)


@pytest.mark.asyncio
async def test_timeouts_and_cancellation():
    async def slow(request):
        await asyncio.sleep(10)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        router = api.Router(api_key="secret", client=client, fallback=fallback, jev_timeout=0.01)
        assert (await router.route("private", CRITERIA)).origin == "fallback"
        task = asyncio.create_task(router.route("private", CRITERIA))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with pytest.raises(api.FallbackError):
        await run(payload(confidence=0.1), fallback_fn=slow, fallback_timeout=0.01)


@pytest.mark.asyncio
async def test_observer_metadata_only_and_nonfatal():
    events = []

    class Observer:
        def on_decision(self, event):
            events.append(event)
            raise RuntimeError("observer unavailable")

    await run(payload(), observer=Observer())
    event = events[0]
    assert set(event.model_dump()) == {
        "origin",
        "reason",
        "jev_ms",
        "fallback_ms",
        "input_tokens",
        "output_tokens",
        "jev_reason",
        "jev_error",
        "jev_http_status",
        "jev_usage",
        "jev_probability_sum",
    }
    assert event.jev_error is None
    assert event.jev_http_status == 200
    assert event.jev_reason == "confident"
    assert "private" not in event.model_dump_json()
    assert "secret" not in event.model_dump_json()


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_configuration(threshold):
    with pytest.raises(ValueError):
        api.Router(api_key="key", fallback=fallback, threshold=threshold)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(api.ConfigurationError, match="TYPESAFE_API_KEY"):
        api.Router(fallback=fallback)


@pytest.mark.asyncio
async def test_invalid_input_rejected_before_http():
    for criteria in [{}, {"": "empty"}, {str(i): "x" for i in range(256)}]:
        with pytest.raises(ValueError):
            await api.Router(api_key="key", fallback=fallback).route("x", criteria)


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
async def test_nonfinite_confidence_rejected(number):
    raw = (
        '{"answers":{"route":{"type":"choice","choice":"billing","confidence":'
        + number
        + ',"probabilities":{"billing":0.88,"technical":0.12}}}}'
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=raw))
    ) as client:
        assert (
            await api.Router(api_key="key", client=client, fallback=fallback).route("x", CRITERIA)
        ).origin == "fallback"
