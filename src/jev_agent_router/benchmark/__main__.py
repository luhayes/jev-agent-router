"""Run with python -m jev_agent_router.benchmark."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from jev_agent_router import RouterError
from .data import digest, prepare, write_json
from .report import DEFAULT_THRESHOLDS, analyze
from .runner import collect


async def demo(output):
    """Exercise actual HTTP parsing and Router logic with explicitly fake responses."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    dataset = output / "dataset"
    dataset.mkdir()
    criteria = {"billing": "Billing and payments", "technical": "Product errors", "account": "Account access"}
    splits = {}
    cases = {}
    for split in ("dev", "test"):
        samples = []
        for i in range(12):
            label = list(criteria)[i % 3]
            text = f"Synthetic {split} case {i}"
            samples.append({"id": f"{split}:{i}", "text": text, "label": label})
            cases[text] = (i, label)
        splits[split] = samples
        write_json(dataset / f"{split}.json", samples)
    manifest = {
        "schema_version": 1,
        "dataset": "SYNTHETIC — NOT BANKING77",
        "synthetic": True,
        "criteria": criteria,
        "instructions": "Select the matching demo category.",
        "splits": {s: {"count": len(v), "sha256": digest(v)} for s, v in splits.items()},
    }
    write_json(dataset / "manifest.json", manifest)

    def handler(request):
        payload = json.loads(request.content)
        if request.url.host == "api.typesafe.ai":
            i, label = cases[payload["state"]]
            low = i % 4 == 0
            selected = list(criteria)[(i + 1) % 3] if low else label
            probabilities = {k: 0.1 for k in criteria}
            probabilities[selected] = 0.8
            return httpx.Response(
                200,
                json={
                    "answers": {
                        "route": {
                            "type": "choice",
                            "choice": selected,
                            "confidence": 0.65 if low else 0.95,
                            "probabilities": probabilities,
                        }
                    },
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                },
            )
        if request.url.host != "api.openai.com":
            raise AssertionError("Unexpected network destination in demo")
        state = json.loads(payload["messages"][1]["content"])["state"]
        _, label = cases[state]
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"label": label})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    prices = {
        "as_of": "2026-01-01",
        "source": "Synthetic arithmetic fixtures; NOT vendor prices",
        "jev": {"model": "jev-latest", "input_per_million": 0.1, "output_per_million": 0},
        "llm": {"model": "synthetic-llm", "input_per_million": 1, "output_per_million": 2},
    }
    write_json(output / "synthetic-prices.json", prices)
    transport = httpx.MockTransport(handler)
    for split in ("dev", "test"):
        await collect(dataset, split, output / f"{split}-run", "synthetic-llm", transport=transport)
        analyze(
            output / f"{split}-run",
            output / f"{split}-report",
            prices_path=output / "synthetic-prices.json",
            policy_path=output / "dev-report/policy.json" if split == "test" else None,
        )
    await collect(
        dataset,
        "test",
        output / "live-run",
        "synthetic-llm",
        transport=transport,
        policy_path=output / "dev-report/policy.json",
    )
    analyze(output / "live-run", output / "live-report", policy_path=output / "dev-report/policy.json")
    print(f"SYNTHETIC demo only. Reports: {output / 'test-report/report.md'}")


def parser():
    root = argparse.ArgumentParser(
        description="Local BANKING77 benchmark; no telemetry, no automatic paid calls."
    )
    sub = root.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="Download pinned public CSVs or use local files")
    prepare_parser.add_argument("--output", required=True, type=Path)
    prepare_parser.add_argument("--data-dir", type=Path)
    prepare_parser.add_argument("--seed", type=int, default=42)
    prepare_parser.add_argument("--dev-per-class", type=int, default=5)
    prepare_parser.add_argument(
        "--test-per-class", type=int, default=10, help="0 uses all non-overlapping test rows"
    )
    prepare_parser.add_argument("--smoke-size", type=int, default=20)
    run_parser = sub.add_parser("collect", help="Make PAID provider calls using environment credentials")
    run_parser.add_argument("--dataset", required=True, type=Path)
    run_parser.add_argument("--split", choices=("smoke", "dev", "test"), required=True)
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument("--model", required=True, help="OpenAI model supporting strict JSON schema")
    run_parser.add_argument("--timeout", type=float, default=30)
    run_parser.add_argument("--delay", type=float, default=0, help="Seconds between samples")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument(
        "--policy",
        dest="policy_path",
        type=Path,
        help="Measure the actual cascade using a frozen policy instead of paired calls",
    )
    report_parser = sub.add_parser("analyze", help="Offline analysis; test split requires frozen dev policy")
    report_parser.add_argument("--run", dest="run_dir", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    report_parser.add_argument("--prices", dest="prices_path", type=Path)
    report_parser.add_argument("--policy", dest="policy_path", type=Path)
    report_parser.add_argument("--thresholds", nargs="+", type=float, default=DEFAULT_THRESHOLDS)
    report_parser.add_argument(
        "--max-drop",
        type=float,
        default=0.01,
        help="Allowed dev accuracy drop as a fraction, not a quality guarantee",
    )
    demo_parser = sub.add_parser("demo", help="No-network synthetic demo through actual Router and fallback")
    demo_parser.add_argument("--output", required=True, type=Path)
    return root


def main(argv=None):
    args = vars(parser().parse_args(argv))
    command = args.pop("command")
    try:
        if command == "prepare":
            result = prepare(**args)
            print(json.dumps(result["splits"], indent=2))
        elif command == "collect":
            asyncio.run(collect(**args))
        elif command == "analyze":
            result = analyze(**args)
            print(result["selection_status"])
        else:
            asyncio.run(demo(**args))
    except KeyboardInterrupt:
        print("Interrupted; completed rows are saved. Use collect --resume to continue.", file=sys.stderr)
        return 130
    except ImportError:
        print("Benchmark dependency missing; for SOCKS proxies install httpx[socks].", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError, RouterError, httpx.HTTPError) as exc:
        # Do not print raw provider bodies or credentials embedded in environment settings.
        if isinstance(exc, (httpx.HTTPError, OSError, KeyError, TypeError)):
            message = f"{type(exc).__name__}: check local files, schema, permissions or network access"
        else:
            message = str(exc)
        print(f"Benchmark error: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
