import json

import httpx
import pytest

from jev_agent_router import ConfigurationError, FallbackError, RouteRequest
from jev_agent_router.llm import ChatJSONFallback, PROVIDERS


CASES = [
    ("openai", "https://api.openai.com/v1/chat/completions", "json_schema", "OPENAI_API_KEY"),
    ("deepseek", "https://api.deepseek.com/chat/completions", "json_object", "DEEPSEEK_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "json_schema", "OPENROUTER_API_KEY"),
    (
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "json_schema",
        "GEMINI_API_KEY",
    ),
    ("kimi", "https://api.moonshot.ai/v1/chat/completions", "json_object", "MOONSHOT_API_KEY"),
    ("kimi-cn", "https://api.moonshot.cn/v1/chat/completions", "json_object", "MOONSHOT_API_KEY"),
]
REQUEST = RouteRequest(
    state="private state", criteria={"billing": "Payments", "technical": "Bugs"}, instructions="Route."
)


@pytest.mark.parametrize("provider,url,mode,key", CASES)
async def test_provider_request_contract_and_key_isolation(monkeypatch, provider, url, mode, key):
    for _, key_name, _ in PROVIDERS.values():
        monkeypatch.setenv(key_name, "wrong-provider-key")
    monkeypatch.setenv(key, "selected-key")

    def handler(request):
        assert str(request.url) == url
        assert request.headers["Authorization"] == "Bearer selected-key"
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == mode
        assert payload["model"] == "account-model"
        if mode == "json_object":
            assert "JSON object" in payload["messages"][0]["content"]
            assert '{"label":' in payload["messages"][0]["content"]
        else:
            assert payload["response_format"]["json_schema"]["schema"]["properties"]["label"]["enum"] == list(
                REQUEST.criteria
            )
        if provider == "openrouter":
            assert payload["provider"] == {"require_parameters": True}
        else:
            assert "provider" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"label":"billing"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        choice = await ChatJSONFallback(provider=provider, model="account-model", client=client)(REQUEST)
    assert choice.label == "billing"
    assert choice.usage.input_tokens == 10
    assert choice.usage.output_tokens == 3
    # Another provider's key must never be used when this key is absent.
    monkeypatch.delenv(key)
    with pytest.raises(ConfigurationError, match=key):
        ChatJSONFallback(provider=provider, model="account-model")


@pytest.mark.parametrize(
    "content,finish,refusal",
    [
        ('{"label":"outside"}', "stop", None),
        ('{"label":"billing","extra":1}', "stop", None),
        ('{"label":1}', "stop", None),
        ("", "stop", None),
        ('```json\n{"label":"billing"}\n```', "stop", None),
        ('{"label":"billing"}', "length", None),
        ('{"label":"billing"}', "stop", "refused"),
    ],
)
async def test_json_mode_still_validates_exact_label(content, finish, refusal):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {
                            "content": content,
                            "refusal": refusal,
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FallbackError):
            await ChatJSONFallback(provider="deepseek", api_key="key", model="test", client=client)(REQUEST)


@pytest.mark.parametrize("status", [302, 400, 401, 429, 500])
async def test_no_redirect_retry_or_silent_format_downgrade(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://example.com/leak"}, text="SECRET_BODY")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(FallbackError) as exc:
            await ChatJSONFallback(provider="openrouter", api_key="SECRET_KEY", model="test", client=client)(
                REQUEST
            )
    assert len(calls) == 1
    assert "SECRET" not in str(exc.value)


async def test_explicit_format_override_and_unknown_usage():
    def handler(request):
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"label":"billing"}',
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ChatJSONFallback(
            provider="gemini", response_format="json_object", api_key="key", model="test", client=client
        )(REQUEST)
    assert result.usage.input_tokens is None and result.usage.output_tokens is None


@pytest.mark.parametrize("kwargs", [{"provider": "other"}, {"response_format": "text"}])
def test_invalid_provider_or_format_fails_before_network(kwargs):
    with pytest.raises(ConfigurationError):
        ChatJSONFallback(model="test", api_key="key", **kwargs)
