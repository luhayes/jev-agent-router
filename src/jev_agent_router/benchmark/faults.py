"""Offline contract experiment through real Router and ChatJSONFallback code.

The baseline is the SAME validated Router with threshold=0 and no fallback.
This isolates policy behavior, not the value of this SDK over every custom router.
"""

import asyncio
import json
import hashlib
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx

from jev_agent_router import (
    AbstentionError, FallbackError, JevRequestError, Router, __version__,
)
from jev_agent_router.llm import ChatJSONFallback
from .data import digest, write_json
from .report import percentile

CRITERIA = {"billing": "Payments and invoices", "technical": "Product faults"}
TIMEOUT = 0.05


@dataclass(frozen=True)
class Scenario:
    name: str
    jev: str = "healthy"
    llm: str = "healthy"
    cancel_at: str | None = None


SCENARIOS = (
    Scenario("healthy"),
    Scenario("low_confidence_corrected", "low_wrong"),
    Scenario("confidently_wrong", "high_wrong"),
    Scenario("fallback_can_regress", "low_correct", "wrong"),
    Scenario("rate_limit", "429"),
    Scenario("server_error", "503"),
    Scenario("jev_timeout", "timeout"),
    Scenario("network_error", "network"),
    Scenario("invalid_json", "json"),
    Scenario("unknown_label", "label"),
    Scenario("invalid_probability_sum", "sum"),
    Scenario("authentication_error", "401"),
    Scenario("fallback_timeout", "low_correct", "timeout"),
    Scenario("fallback_server_error", "low_correct", "503"),
    Scenario("fallback_invalid_label", "low_correct", "label"),
    Scenario("cancel_during_jev", cancel_at="jev"),
    Scenario("cancel_during_fallback", "low_correct", cancel_at="llm"),
)


class Capture:
    def __init__(self):
        self.events = []

    def on_decision(self, event):
        self.events.append(event.model_dump())


def expected(scenario, strategy):
    """Explicit behavior contract, independent of observed outcomes."""
    baseline = strategy == "jev-only"
    if scenario.cancel_at:
        return ("cancelled", None, "cancelled", "cancelled", int(scenario.cancel_at == "llm"))
    if scenario.jev == "401":
        return ("request_error", None, "error", "jev_request_error", 0)
    valid = scenario.jev in ("healthy", "low_wrong", "low_correct", "high_wrong")
    if baseline:
        if not valid:
            return ("abstained", None, "error", "no_fallback", 0)
        label = "technical" if scenario.jev in ("low_wrong", "high_wrong") else "billing"
        return ("decision", label, "jev", "confident", 0)
    if scenario.jev in ("healthy", "high_wrong"):
        return ("decision", "technical" if scenario.jev == "high_wrong" else "billing", "jev", "confident", 0)
    if scenario.llm in ("timeout", "503", "label"):
        return ("fallback_error", None, "error", "fallback_failed", 1)
    reason = "low_confidence" if valid else (
        "invalid_response" if scenario.jev in ("json", "label", "sum") else "jev_transient_error"
    )
    return ("decision", "technical" if scenario.llm == "wrong" else "billing", "fallback", reason, 1)


async def exercise(scenario, strategy, repeat):
    counts = {"jev": 0, "llm": 0}
    entered = asyncio.Event()
    observed_cancel = []

    async def handler(request):
        host = request.url.host
        if host not in ("api.typesafe.ai", "api.openai.com"):
            raise AssertionError("Unexpected mock destination")
        provider = "jev" if host == "api.typesafe.ai" else "llm"
        counts[provider] += 1
        fault = scenario.jev if provider == "jev" else scenario.llm
        if scenario.cancel_at == provider:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed_cancel.append(provider)
                raise
        if fault == "timeout":
            await asyncio.sleep(TIMEOUT * 20)
        if fault == "network":
            raise httpx.ConnectError("synthetic network failure", request=request)
        if fault in ("429", "503", "401"):
            return httpx.Response(int(fault), json={"error": "synthetic fixture"})
        if fault == "json":
            return httpx.Response(200, content=b"not-json")
        if provider == "llm":
            label = "unknown" if fault == "label" else "technical" if fault == "wrong" else "billing"
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"label": label})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            })
        label = "unknown" if fault == "label" else "technical" if fault in ("low_wrong", "high_wrong") else "billing"
        return httpx.Response(200, json={
            "answers": {"route": {
                "type": "choice", "choice": label,
                "confidence": 0.4 if fault.startswith("low_") else 0.95,
                "probabilities": {"billing": 0.2 if fault == "sum" else 0.6, "technical": 0.4},
            }},
            "usage": {"input_tokens": 10, "output_tokens": 0},
        })

    capture = Capture()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        fallback = ChatJSONFallback(model="synthetic-fallback", api_key="offline-only", client=client, timeout=1)
        async with Router(
            api_key="offline-only", client=client, observer=capture,
            fallback=None if strategy == "jev-only" else fallback,
            threshold=0 if strategy == "jev-only" else 0.8,
            jev_timeout=TIMEOUT, fallback_timeout=TIMEOUT,
        ) as router:
            started = perf_counter()
            task = asyncio.create_task(router.route("Synthetic request", CRITERIA))
            if scenario.cancel_at:
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
            label = origin = reason = None
            try:
                decision = await task
                status, label, origin, reason = "decision", decision.label, decision.origin, decision.reason
            except asyncio.CancelledError:
                status = "cancelled"
            except AbstentionError:
                status = "abstained"
            except JevRequestError:
                status = "request_error"
            except FallbackError:
                status = "fallback_error"
            elapsed_ms = (perf_counter() - started) * 1000
    event = capture.events[-1] if capture.events else {}
    origin, reason = origin or event.get("origin"), reason or event.get("reason")
    actual = (status, label, origin, reason, counts["llm"])
    contract = expected(scenario, strategy)
    diagnostics = {
        "429": "http_error", "503": "http_error", "401": "http_error",
        "timeout": "timeout", "network": "network_error", "json": "invalid_json",
        "label": "invalid_labels", "sum": "invalid_probability_sum",
    }
    checks = {
        "outcome_contract": actual == contract,
        "one_jev_attempt": counts["jev"] == 1,
        "at_most_one_fallback": counts["llm"] <= 1,
        "one_observer_event": len(capture.events) == 1,
        "allowed_label_or_no_decision": label is None or label in CRITERIA,
        "jev_diagnostic": event.get("jev_error") == diagnostics.get(scenario.jev),
        "cancellation_propagated": not scenario.cancel_at or observed_cancel == [scenario.cancel_at],
    }
    return {
        "scenario": scenario.name, "strategy": strategy, "repeat": repeat,
        "truth": "billing", "status": status, "label": label, "origin": origin, "reason": reason,
        "correct": status == "decision" and label == "billing", "calls": counts,
        "elapsed_ms": elapsed_ms, "event": event,
        "expected": dict(zip(("status", "label", "origin", "reason", "llm_calls"), contract)),
        "checks": checks, "passed": all(checks.values()),
    }


def render(report):
    lines = [
        "# Offline routing fault experiment", "",
        "**Synthetic fixtures, not provider reliability or production latency. No API keys or network calls.**", "",
        "Baseline: the same validated Router, threshold 0, no fallback. Cascade: threshold 0.8 with the real",
        "ChatJSONFallback parser. Only the policy changes; this does not compare the SDK to every custom implementation.", "",
        f"Contract checks: {report['checks_passed']}/{report['checks_total']}. Repeats: {report['repeats']}.",
        "HTTP request counts are mocked provider attempts, not billable calls. No retries.", "",
        "| Scenario | Strategy | Outcome | Label | Jev / LLM calls | Diagnostic | Contract |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        if row["repeat"] != 0:
            continue
        diagnostic = row["event"].get("jev_error") or row["reason"]
        lines.append(f"| {row['scenario']} | {row['strategy']} | {row['status']} | {row['label'] or '—'} | "
                     f"{row['calls']['jev']} / {row['calls']['llm']} | {diagnostic} | "
                     f"{'PASS' if row['passed'] else 'FAIL'} |")
    lines += ["", "## Observed local timings", "",
              "Includes successes, intentional failures and cancellations. Timeouts are injected at 50 ms;",
              "timings depend on the local scheduler, and are not SDK overhead estimates or provider comparisons.", "",
              "| Strategy | Executions | Decisions returned | Correct fixture decisions | P50 ms | P95 ms |",
              "|---|---:|---:|---:|---:|---:|"]
    for item in report["summaries"]:
        lines.append(f"| {item['strategy']} | {item['executions']} | {item['decisions']} | {item['correct']} | "
                     f"{item['p50_ms']:.3f} | {item['p95_ms']:.3f} |")
    lines += ["", "## What this establishes", "",
              "- Recoverable transport/response faults can reach a validated fallback, with bounded attempt counts.",
              "- HTTP 401 stops without fallback. Cancellation propagates. Invalid fallback output returns an error.",
              "- A confidently wrong Jev answer remains wrong. A fallback can replace a correct answer with a wrong one.",
              "- Contract PASS includes expected errors; it does not mean every request returned a correct decision.",
              "- The fallback-stage cancellation case has no Jev-only execution because that baseline never calls a fallback.",
              "- The scenario mix is hand-picked, not a measured incident distribution; do not advertise aggregate reliability gains.",
              "- Returned labels are data. This experiment does not authorize or execute tools.", "",
              "Reproduce: `python -m jev_agent_router.benchmark faults --output benchmark-results/faults --repeats 3`.",
              "`report.json` includes all repeated rows, expected outcomes, sanitized observer events and checks.", ""]
    return "\n".join(lines)


async def run_experiment(output, repeats=3):
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeats must be an integer from 1 to 100")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for repeat in range(repeats):
        for scenario in SCENARIOS:
            strategies = ["jev-only", "cascade"] if repeat % 2 == 0 else ["cascade", "jev-only"]
            for strategy in strategies:
                if strategy == "jev-only" and scenario.cancel_at == "llm":
                    continue
                rows.append(await exercise(scenario, strategy, repeat))
    summaries = []
    for strategy in ("jev-only", "cascade"):
        group = [r for r in rows if r["strategy"] == strategy]
        summaries.append({
            "strategy": strategy, "executions": len(group),
            "decisions": sum(r["status"] == "decision" for r in group),
            "correct": sum(r["correct"] for r in group),
            "p50_ms": percentile([r["elapsed_ms"] for r in group], 0.5),
            "p95_ms": percentile([r["elapsed_ms"] for r in group], 0.95),
        })
    checks = [passed for row in rows for passed in row["checks"].values()]
    report = {
        "schema_version": 1, "synthetic": True, "network": "httpx.MockTransport only",
        "telemetry": "disabled", "sdk_version": __version__, "python": platform.python_version(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "scenario_sha256": digest([asdict(s) for s in SCENARIOS]),
        "source_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in {
                "faults.py": Path(__file__),
                "router.py": Path(__file__).parents[1] / "__init__.py",
                "llm.py": Path(__file__).parents[1] / "llm.py",
            }.items()
        },
        "timeouts_seconds": {"jev": TIMEOUT, "fallback": TIMEOUT},
        "repeats": repeats, "scenario_count": len(SCENARIOS),
        "checks_total": len(checks), "checks_passed": sum(checks), "passed": all(checks),
        "summaries": summaries, "rows": rows,
    }
    write_json(output / "report.json", report)
    (output / "report.md").write_text(render(report), encoding="utf-8")
    return report
