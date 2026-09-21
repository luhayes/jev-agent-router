"""Offline demonstration with explicitly synthetic HTTP fixtures, no API calls."""

import asyncio
import httpx
from jev_agent_router import Router, FallbackChoice


async def main():
    async def fallback(request):
        # Demo policy, NOT an LLM and NOT an accuracy guarantee.
        return FallbackChoice(label="human_review")

    def fixture(request):
        confidence = 0.9 if b"invoice" in request.content else 0.3
        return httpx.Response(
            200,
            json={
                "answers": {
                    "route": {
                        "type": "choice",
                        "choice": "billing",
                        "confidence": confidence,
                        "probabilities": {"billing": 0.9, "human_review": 0.1},
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture)) as client:
        router = Router(api_key="offline-placeholder", fallback=fallback, client=client)
        for state in ("invoice please", "unclear request"):
            decision = await router.route(
                state, {"billing": "Payment questions", "human_review": "Needs review"}
            )
            print(decision.model_dump_json())


if __name__ == "__main__":
    asyncio.run(main())
