"""Shared construction and validation for CLI and MCP. No provider text logging."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import math
import os

import httpx
from jev_agent_router import ConfigurationError, RouteRequest, Router
from jev_agent_router.openai import OpenAIJSONFallback


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only-offline", action="store_true", help="Synthetic transport; NEVER a live provider result")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    # Prevent dependency request logging from leaking prompts or credentials.
    logging.disable(logging.CRITICAL)
    return args


@asynccontextmanager
async def router_context(test_only=False):
    if test_only:
        def synthetic(request):
            criteria = json.loads(request.content)["questions"]["route"]["criteria"]
            label = next(iter(criteria))
            return httpx.Response(200, json={"answers": {"route": {
                "type": "choice", "choice": label, "confidence": 1.0,
                "probabilities": {k: float(k == label) for k in criteria},
            }}})

        async def never_fallback(request):
            raise RuntimeError("Synthetic fixture unexpectedly required fallback")

        async with httpx.AsyncClient(transport=httpx.MockTransport(synthetic)) as client:
            async with Router(api_key="synthetic-test-only-not-a-key", client=client, fallback=never_fallback) as router:
                yield router
    else:
        model = os.getenv("JEV_FALLBACK_MODEL", "")
        if not model:
            raise ConfigurationError("Set JEV_FALLBACK_MODEL")
        async with Router(fallback=OpenAIJSONFallback(model=model), jevcalc_api_key=os.getenv("JEVCALC_API_KEY") or None) as router:
            yield router


async def decide(router, payload, *, timeout=45.0, test_only=False):
    request = RouteRequest.model_validate(payload)
    async with asyncio.timeout(timeout):
        decision = await router.route(request.state, request.criteria, instructions=request.instructions)
    return {"test_only": test_only, "decision": decision.model_dump(mode="json")}
