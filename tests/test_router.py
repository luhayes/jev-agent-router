import importlib.util
import json
import httpx
import pytest


def test_package_exists():
    assert importlib.util.find_spec("jev_agent_router") is not None, "Choice router package not implemented"


@pytest.mark.asyncio
async def test_confident_choice_uses_real_api_confidence():
    from jev_agent_router import Router

    async def fallback(request):
        pytest.fail("confident choice must not call fallback")

    def handler(request):
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "state": "invoice",
            "model": "jev-latest",
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": "Route support",
                    "criteria": {"billing": "Payments", "technical": "Bugs"},
                }
            },
        }
        return httpx.Response(
            200,
            json={
                "answers": {
                    "route": {
                        "type": "choice",
                        "choice": "billing",
                        "confidence": 0.8,
                        "probabilities": {"billing": 0.9, "technical": 0.1},
                    }
                },
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        router = Router(api_key="test-key", fallback=fallback, client=client)
        result = await router.route(
            "invoice", {"billing": "Payments", "technical": "Bugs"}, instructions="Route support"
        )
    assert result.label == "billing"
    assert result.confidence == 0.8
    assert result.origin == "jev"
    assert result.usage.input_tokens == 10
