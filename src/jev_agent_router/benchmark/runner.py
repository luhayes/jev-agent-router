"""Real Router/fallback execution, resumable local JSONL, no analytics upload."""

import asyncio
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx

from jev_agent_router import (
    ConfigurationError,
    PROBABILITY_SUM_TOLERANCE,
    DecisionEvent,
    FallbackError,
    JevRequestError,
    RouteRequest,
    Router,
    Usage,
    __version__,
)
from jev_agent_router.llm import ChatJSONFallback, PROVIDERS, provider_config
from .data import digest, load_split, read_json, write_json


class Capture:
    def __init__(self):
        self.event: DecisionEvent | None = None

    def on_decision(self, event):
        self.event = event


async def unavailable_fallback(request):
    # Probe only: reaching here marks a recoverable Jev failure without calling an LLM.
    raise FallbackError("Benchmark probe: no fallback executed")


def read_records(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (ValueError, TypeError):
        raise ValueError("Invalid results JSONL; preserve it and use a fresh run directory") from None


async def measure_llm(fallback, request):
    start = perf_counter()
    try:
        choice = await fallback(request)
        return {
            "label": choice.label,
            "usage": choice.usage.model_dump(),
            "status": "ok",
            "elapsed_ms": (perf_counter() - start) * 1000,
        }
    except FallbackError:
        return {
            "label": None,
            "usage": Usage().model_dump(),
            "status": "fallback_failed",
            "elapsed_ms": (perf_counter() - start) * 1000,
        }


async def measure_router(router, request, capture):
    start = perf_counter()
    try:
        decision = await router.route(request.state, request.criteria, instructions=request.instructions)
        result = {
            "label": decision.label,
            "status": "ok",
            "origin": decision.origin,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "usage": decision.usage.model_dump(),
            "fallback_usage": decision.fallback_usage.model_dump() if decision.fallback_usage else None,
        }
    except (JevRequestError, FallbackError) as exc:
        result = {
            "label": None,
            "status": "request_error" if isinstance(exc, JevRequestError) else "recoverable_error",
            "origin": "error",
            "reason": capture.event.jev_reason if capture.event else "unknown",
            "outcome_reason": capture.event.reason if capture.event else "unknown",
            "confidence": None,
            "usage": capture.event.jev_usage.model_dump() if capture.event else Usage().model_dump(),
            "fallback_usage": None,
        }
        if isinstance(exc, JevRequestError):
            result["http_status"] = exc.status_code
    result["elapsed_ms"] = (perf_counter() - start) * 1000
    if capture.event:
        result["jev_error"] = capture.event.jev_error
        result["http_status"] = capture.event.jev_http_status
        result["probability_sum"] = capture.event.jev_probability_sum
        result["jev_ms"] = capture.event.jev_ms
        result["fallback_ms"] = capture.event.fallback_ms
    return result


def policy_strategy(policy):
    """Read legacy cascade policies without silently accepting malformed v2 policies."""
    version = policy.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported policy schema version")
    strategy = policy.get("strategy", "cascade") if version == 1 else policy.get("strategy")
    if strategy not in ("jev-only", "llm-only", "cascade") or (version == 1 and strategy != "cascade"):
        raise ValueError("Invalid frozen strategy")
    threshold = policy.get("threshold")
    if strategy == "cascade":
        if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not 0 <= threshold <= 1:
            raise ValueError("Invalid frozen threshold")
    elif threshold is not None:
        raise ValueError("Single-provider policies must have a null threshold")
    diagnostic = policy.get("diagnostic_cascade_threshold")
    if diagnostic is not None and (
        isinstance(diagnostic, bool) or not isinstance(diagnostic, (int, float)) or not 0 <= diagnostic <= 1
    ):
        raise ValueError("Invalid diagnostic cascade threshold")
    if strategy == "cascade" and diagnostic is not None and diagnostic != threshold:
        raise ValueError("Cascade diagnostic must match the selected threshold")
    return strategy


def check_policy(policy, config):
    policy_strategy(policy)
    for key in ("dataset_hash", "model", "jev_model", "timeout", "synthetic", "sdk_version"):
        if policy["config"][key] != config[key]:
            raise ValueError(f"Frozen policy mismatch: {key}")
    if policy["config"].get("llm", provider_config()) != config.get("llm", provider_config()):
        raise ValueError("Frozen policy mismatch: LLM provider or response format")
    if policy["config"].get("diagnostics_version", 0) != config.get("diagnostics_version", 0):
        raise ValueError("Frozen policy mismatch: diagnostics version; use the original collector commit")
    tolerance_key = "jev_probability_sum_tolerance"
    if policy["config"].get(tolerance_key, 1e-6) != config.get(tolerance_key, 1e-6):
        raise ValueError("Frozen policy mismatch: Jev probability-sum tolerance; select a new policy")
    if policy.get("selection_split") != "dev":
        raise ValueError("Policy must be selected on development data")


async def collect(
    dataset,
    split,
    output,
    model,
    timeout=30,
    delay=0,
    resume=False,
    policy_path=None,
    transport=None,
    provider="openai",
    response_format="auto",
):
    if not model.strip() or not 0 < timeout < float("inf") or not 0 <= delay < float("inf"):
        raise ValueError("Require model, positive finite timeout and nonnegative finite delay")
    llm_config = provider_config(provider, response_format)
    key_name = PROVIDERS[provider][1]
    manifest, samples = load_split(dataset, split)
    synthetic = manifest.get("synthetic", False)
    if synthetic != (transport is not None):
        raise ValueError(
            "Synthetic datasets require the isolated demo transport; real data requires live providers"
        )
    config = {
        "schema_version": 1,
        "diagnostics_version": 1,
        "jev_probability_sum_tolerance": PROBABILITY_SUM_TOLERANCE,
        "dataset_hash": digest(manifest),
        "split": split,
        "model": model,
        "llm": llm_config,
        "jev_model": "jev-latest",
        "timeout": timeout,
        "delay": delay,
        "synthetic": synthetic,
        "sdk_version": __version__,
        "mode": "cascade-live" if policy_path else "paired",
    }
    if policy_path:
        policy = read_json(policy_path)
        check_policy(policy, config)
        config["policy_hash"] = digest(policy)
        config["threshold"] = policy["threshold"]
        if policy.get("schema_version", 1) == 2:
            config["mode"] = "policy-live"
            config["strategy"] = policy_strategy(policy)
    strategy = config.get("strategy", "cascade" if policy_path else "paired")
    required_keys = (
        ("TYPESAFE_API_KEY",) if strategy == "jev-only"
        else (key_name,) if strategy == "llm-only"
        else ("TYPESAFE_API_KEY", key_name)
    )
    if not synthetic and any(not os.getenv(k, "").strip() for k in required_keys):
        raise ConfigurationError(f"Set {' and '.join(required_keys)} in your environment")
    output = Path(output)
    if output.exists() and not resume:
        raise ValueError("Run directory exists; use --resume or a new output directory")
    if resume and not (output / "run.json").exists():
        raise ValueError("Cannot resume without run.json")
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".running"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(
            "Run is locked; remove .running only after verifying no collector is active"
        ) from None
    os.close(lock_fd)
    try:
        if resume:
            run = read_json(output / "run.json")
            if run["config"] != config:
                raise ValueError("Resume configuration differs from the original run")
        else:
            run = {
                "config": config,
                "dataset": manifest,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(),
                "sample_ids": [r["id"] for r in samples],
                "complete": False,
                "telemetry": "disabled",
            }
            write_json(output / "run.json", run)
        records = read_records(output / "results.jsonl")
        completed = {r["id"] for r in records}
        if len(completed) != len(records) or not completed <= set(run["sample_ids"]):
            raise ValueError("Duplicate or unexpected result IDs")
        if any(r["truth"] != next(s["label"] for s in samples if s["id"] == r["id"]) for r in records):
            raise ValueError("Result labels differ from dataset")
        async with httpx.AsyncClient(transport=transport) as client:
            fallback = None if strategy == "jev-only" else ChatJSONFallback(
                provider=provider,
                response_format=response_format,
                model=model,
                api_key="synthetic" if synthetic else None,
                client=client,
                timeout=timeout,
            )
            with (output / "results.jsonl").open("a", encoding="utf-8") as stream:
                for i, sample in enumerate(samples):
                    if sample["id"] in completed:
                        continue
                    request = RouteRequest(
                        state=sample["text"],
                        criteria=manifest["criteria"],
                        instructions=manifest["instructions"],
                    )
                    capture = Capture()
                    if strategy == "llm-only":
                        llm = await measure_llm(fallback, request)
                    else:
                        async with Router(
                            api_key="synthetic" if synthetic else None,
                            client=client,
                            fallback=fallback if strategy == "cascade" else unavailable_fallback,
                            threshold=config.get("threshold") or 0,
                            jev_timeout=timeout,
                            fallback_timeout=timeout,
                            observer=capture,
                        ) as router:
                            # Alternate paired order; single-provider policies never call the other provider.
                            if not policy_path and i % 2:
                                llm = await measure_llm(fallback, request)
                            jev = await measure_router(router, request, capture)
                            if not policy_path and not i % 2:
                                llm = await measure_llm(fallback, request)
                    record = {"id": sample["id"], "truth": sample["label"]}
                    if strategy == "llm-only":
                        record["llm"] = llm
                    elif strategy == "jev-only":
                        record["jev"] = jev
                    elif policy_path:
                        record["cascade"] = jev
                    else:
                        record.update(jev=jev, llm=llm)
                    stream.write(json.dumps(record, allow_nan=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    print(f"{split}: {i + 1}/{len(samples)}", flush=True)
                    if delay:
                        await asyncio.sleep(delay)
        run["complete"] = True
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run.json", run)
    finally:
        lock.unlink()
    return run
