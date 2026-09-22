"""Manual Actions orchestration; model credentials are read only by the collector."""

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jev_agent_router import ConfigurationError
from jev_agent_router.llm import PROVIDERS, provider_config
from jev_agent_router.benchmark.__main__ import demo
from jev_agent_router.benchmark.data import prepare, write_json
from jev_agent_router.benchmark.report import analyze, validate_prices
from jev_agent_router.benchmark.runner import collect

ROOT = Path("benchmark-results/actions")
SIZES = {"small": (2, 2), "standard": (5, 10), "full-test": (5, 0)}
# Cancel cooperatively before the job limit so completed JSONL rows can be uploaded.
RUN_TIMEOUT_SECONDS = 300 * 60


@dataclass(frozen=True)
class Settings:
    mode: str
    model: str
    prices: dict | None
    measure_live: bool
    provider: str = "openai"
    response_format: str = "auto"


def settings_from_env(env):
    mode = env.get("BENCHMARK_MODE", "demo")
    if mode not in {"demo", "smoke", *SIZES}:
        raise ValueError("Invalid benchmark mode")
    if mode == "demo":
        return Settings("demo", "", None, False)
    if env.get("BENCHMARK_CONFIRM_PAID", "false").lower() != "true":
        raise ValueError("Live modes require confirm_paid=true")
    provider = env.get("BENCHMARK_PROVIDER", "openai")
    response_format = env.get("BENCHMARK_RESPONSE_FORMAT", "auto")
    try:
        provider_config(provider, response_format)
    except ConfigurationError:
        raise ValueError("Select a supported provider and response_format") from None
    model = env.get("BENCHMARK_MODEL", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model):
        raise ValueError("Provide a valid model ID in model; do not enter credentials")
    live = env.get("BENCHMARK_MEASURE_LIVE", "false").lower() == "true"
    if mode == "smoke" and live:
        raise ValueError("measure_live is available only for small, standard or full-test")
    raw = env.get("BENCHMARK_PRICES_JSON", "").strip()
    prices = None
    if raw:
        try:
            supplied = json.loads(raw)
            # Accept only the pricing contract; reject arbitrary extra fields.
            if set(supplied) != {"as_of", "source", "jev", "llm"}:
                raise ValueError
            for tariff in ("jev", "llm"):
                if set(supplied[tariff]) != {"model", "input_per_million", "output_per_million"}:
                    raise ValueError
            validate_prices(supplied, {"jev_model": "jev-latest", "model": model})
            prices = supplied
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError(
                "Invalid prices_json; use the example schema, matching model IDs and valid rates"
            ) from None
    if mode in SIZES:
        if prices is None or any(
            prices[tariff][rate] is None
            for tariff in ("jev", "llm")
            for rate in ("input_per_million", "output_per_million")
        ):
            raise ValueError("Benchmark modes require complete verified prices_json before paid collection")
    return Settings(mode, model, prices, live, provider, response_format)


def summary(text):
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n\n")


def stage(name):
    print(f"Stage: {name}", flush=True)


def append_report(path):
    if path.exists():
        summary(path.read_text(encoding="utf-8"))


async def execute(settings, root=ROOT):
    if settings.mode == "demo":
        stage("offline synthetic demo")
        await demo(root / "demo")
        append_report(root / "demo/test-report/report.md")
        append_report(root / "demo/live-report/report.md")
        return "completed_demo"

    prices_path = None
    if settings.prices is not None:
        prices_path = root / "prices.json"
        write_json(prices_path, settings.prices)
    dev_count, test_count = SIZES.get(settings.mode, (5, 10))
    stage("prepare pinned public BANKING77 data")
    prepare(root / "data", dev_per_class=dev_count, test_per_class=test_count)

    async def collect_split(split, output, policy=None):
        await collect(
            root / "data",
            split,
            output,
            settings.model,
            policy_path=policy,
            provider=settings.provider,
            response_format=settings.response_format,
        )

    stage("20-sample smoke evaluation")
    await collect_split("smoke", root / "smoke-run")
    smoke = analyze(root / "smoke-run", root / "smoke-report", prices_path=prices_path)
    append_report(root / "smoke-report/report.md")
    if any(r["request_failure_rate"] > 0 for r in smoke["summaries"][:2]):
        summary(
            "**Stopped after smoke:** provider failures were recorded. Inspect the artifacts before another paid run."
        )
        return "stopped_smoke_failures"
    if settings.mode == "smoke":
        return "completed_smoke"

    stage("development collection and threshold selection")
    await collect_split("dev", root / "dev-run")
    dev = analyze(root / "dev-run", root / "dev-report", prices_path=prices_path)
    append_report(root / "dev-report/report.md")
    if dev["selected_threshold"] is None:
        summary(
            "**Stopped after development:** no eligible fully priced threshold. Test and live calls were skipped."
        )
        return "stopped_no_policy"
    policy = root / "dev-report/policy.json"

    stage("held-out test evaluation with frozen policy")
    await collect_split("test", root / "test-run")
    analyze(root / "test-run", root / "test-report", policy_path=policy)
    append_report(root / "test-report/report.md")
    if settings.measure_live:
        stage("additional live cascade measurement")
        await collect_split("test", root / "live-run", policy)
        analyze(root / "live-run", root / "live-report", policy_path=policy)
        append_report(root / "live-report/report.md")
    return "completed_benchmark"


def run(settings, root=ROOT):
    if settings.mode != "demo" and any(
        not os.getenv(key, "").strip() for key in ("TYPESAFE_API_KEY", PROVIDERS[settings.provider][1])
    ):
        raise ValueError(
            f"Add repository Actions secrets TYPESAFE_API_KEY and {PROVIDERS[settings.provider][1]}"
        )
    root.mkdir(parents=True, exist_ok=False)
    write_json(
        root / "provenance.json",
        {
            "repository": os.getenv("GITHUB_REPOSITORY"),
            "commit": os.getenv("GITHUB_SHA"),
            "run_id": os.getenv("GITHUB_RUN_ID"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "mode": settings.mode,
            "llm": provider_config(settings.provider, settings.response_format),
            "measure_live": settings.measure_live,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    outcome = "failed"

    async def bounded():
        async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
            return await execute(settings, root)

    try:
        outcome = asyncio.run(bounded())
        print(f"Result: {outcome}", flush=True)
        summary(
            f"**Run status:** `{outcome}`. Download the `banking77-...` artifact for reports and recovery data."
        )
        return 0
    except BaseException:
        summary(
            "**Run interrupted or failed.** Completed rows are preserved when available. See the artifact for recovery data."
        )
        raise
    finally:
        write_json(
            root / "status.json",
            {
                "status": outcome,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Validate dispatch inputs without credentials or calls"
    )
    args = parser.parse_args(argv)
    try:
        settings = settings_from_env(os.environ)
        if args.check:
            print(f"Validated {settings.mode} settings; no provider calls made.")
            return 0
        return run(settings)
    except KeyboardInterrupt:
        print("Interrupted. Recover completed rows from the run artifact.", file=sys.stderr)
        return 130
    except ValueError as exc:
        # All validation errors above use fixed messages, never raw input JSON.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Provider/network exceptions may include sensitive request details.
        print(
            f"Benchmark failed ({type(exc).__name__}); inspect saved reports or check provider setup.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
