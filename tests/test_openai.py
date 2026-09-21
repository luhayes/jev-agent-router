import importlib.util
import json
import asyncio
import httpx
import pytest
from jev_agent_router import RouteRequest, FallbackError, ConfigurationError


def test_fallback_module_exists():
    assert importlib.util.find_spec("jev_agent_router.openai") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,valid",
    [
        ('{"label":"billing"}', True),
        ('{"label":"other"}', False),
        ('{"label":"billing","confidence":1}', False),
        ("not json", False),
    ],
)
async def test_openai_json_schema(content, valid):
    from jev_agent_router.openai import OpenAIJSONFallback

    def handler(request):
        data = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert data["response_format"]["json_schema"]["strict"] is True
        assert data["response_format"]["json_schema"]["schema"]["properties"]["label"]["enum"] == [
            "billing",
            "technical",
        ]
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fallback = OpenAIJSONFallback(api_key="key", model="test-model", client=client)
        request = RouteRequest(
            state="private", criteria={"billing": "Payments", "technical": "Bugs"}, instructions="route"
        )
        if valid:
            result = await fallback(request)
            assert result.label == "billing"
            assert result.usage.input_tokens == 4
        else:
            with pytest.raises(FallbackError):
                await fallback(request)


@pytest.mark.asyncio
async def test_openai_refusal_timeout_and_key(monkeypatch):
    from jev_agent_router.openai import OpenAIJSONFallback

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        OpenAIJSONFallback(model="test-model")
    request = RouteRequest(state="x", criteria={"a": "A"}, instructions="route")

    async def slow(request):
        await asyncio.sleep(5)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(FallbackError):
            await OpenAIJSONFallback(api_key="key", model="test", client=client, timeout=0.01)(request)
    for message in [{"refusal": "no", "content": '{"label":"a"}'}, {"content": '{"label":"a"}'}]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json={"choices": [{"finish_reason": "length", "message": message}]}
                )
            )
        ) as client:
            with pytest.raises(FallbackError):
                await OpenAIJSONFallback(api_key="key", model="test", client=client)(request)
