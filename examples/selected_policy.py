"""Run one application request with an evaluated policy; PAID unless transport is injected in tests.

python examples/selected_policy.py --dataset benchmark-results/workload \
    --policy benchmark-results/dev-report/policy.json
Read the request as JSON from stdin: {"state": "Where is my invoice?"}.
No tool execution or automatic telemetry. Set credentials only for the selected providers.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from jev_agent_router import PROBABILITY_SUM_TOLERANCE, RouteRequest, Router, RouterError, __version__
from jev_agent_router.benchmark.data import digest, read_json
from jev_agent_router.benchmark.runner import check_policy, policy_strategy
from jev_agent_router.llm import ChatJSONFallback, provider_config


async def decide(manifest, policy, state, *, client=None):
    """The policy binds dataset/criteria, provider, model, timeout and SDK semantics."""
    config = policy["config"]
    llm = config["llm"]
    current = {
        "dataset_hash": digest(manifest), "model": config["model"], "jev_model": "jev-latest",
        "timeout": config["timeout"], "synthetic": False, "sdk_version": __version__,
        "diagnostics_version": 1, "jev_probability_sum_tolerance": PROBABILITY_SUM_TOLERANCE,
        "llm": provider_config(llm["provider"], llm["response_format"]),
    }
    if manifest.get("synthetic"):
        raise ValueError("Use the offline demo for synthetic policies; never send synthetic fixtures live")
    check_policy(policy, current)
    request = RouteRequest(state=state, criteria=manifest["criteria"], instructions=manifest["instructions"])
    strategy = policy_strategy(policy)
    fallback = None if strategy == "jev-only" else ChatJSONFallback(
        provider=llm["provider"], response_format=llm["response_format"],
        model=config["model"], timeout=config["timeout"], client=client,
    )
    if strategy == "llm-only":
        choice = await fallback(request)
        return {"strategy": strategy, "label": choice.label, "origin": "llm", "usage": choice.usage.model_dump()}
    async with Router(
        client=client, fallback=fallback, threshold=policy["threshold"] if strategy == "cascade" else 0,
        jev_timeout=config["timeout"], fallback_timeout=config["timeout"],
    ) as router:
        choice = await router.route(request.state, request.criteria, instructions=request.instructions)
    return {"strategy": strategy, **choice.model_dump()}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or set(payload) != {"state"}:
        raise ValueError('stdin must be an object containing only "state"')
    async with httpx.AsyncClient() as client:
        result = await decide(read_json(args.dataset / "manifest.json"), read_json(args.policy), payload["state"], client=client)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RouterError, ValueError, KeyError, TypeError, OSError):
        print("Decision unavailable; check policy, configuration and provider access. No action executed.", file=sys.stderr)
        raise SystemExit(2)
