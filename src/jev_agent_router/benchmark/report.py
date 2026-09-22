"""Failure-inclusive metrics, development-only selection and held-out reporting."""

import csv
import math
from datetime import date
from pathlib import Path

from .data import digest, read_json, write_json
from .runner import check_policy, read_records


DEFAULT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


def validate_prices(prices, config):
    if prices is None:
        return
    date.fromisoformat(prices["as_of"])
    if not isinstance(prices.get("source"), str) or not prices["source"].strip():
        raise ValueError("Prices require a source description or URL")
    for provider, model in (("jev", config["jev_model"]), ("llm", config["model"])):
        item = prices[provider]
        if item["model"] != model:
            raise ValueError(f"Price model mismatch: {provider}")
        for key in ("input_per_million", "output_per_million"):
            rate = item[key]
            if rate is not None and (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(rate)
                or rate < 0
            ):
                raise ValueError("Prices must be nonnegative finite numbers or null")


def cost(outcome, rates):
    if rates is None:
        return None
    total = 0.0
    for token, price in (("input_tokens", "input_per_million"), ("output_tokens", "output_per_million")):
        rate = rates[price]
        if rate is None:
            return None
        # A caller-supplied zero tariff does not require a provider token count.
        if rate == 0:
            continue
        count = outcome.get("usage", {}).get(token)
        if count is None:
            return None
        total += count * rate / 1_000_000
    return total


def add_cost(*values):
    return None if any(v is None for v in values) else sum(values)


def replay(row, threshold):
    jev, llm = row["jev"], row["llm"]
    if jev["status"] == "ok" and jev["confidence"] >= threshold:
        return jev, False
    if jev["status"] == "request_error":
        return jev, False
    return llm, True


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def wilson(correct, total):
    z = 1.959963984540054
    p = correct / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def summarize(rows, strategy, rates=None, threshold=None):
    costs, latencies, failures, correct, accepted, accepted_errors, fallback = [], [], 0, 0, 0, 0, 0
    per_class = {}
    cascade = strategy == "cascade-replay"
    for row in rows:
        if cascade:
            outcome, used_fallback = replay(row, threshold)
            accepted_here = not used_fallback and row["jev"]["status"] == "ok"
            item_cost = cost(row["jev"], rates["jev"] if rates else None)
            if used_fallback:
                item_cost = add_cost(item_cost, cost(row["llm"], rates["llm"] if rates else None))
        elif strategy == "cascade-live":
            outcome = row["cascade"]
            used_fallback = outcome.get("origin") == "fallback" or outcome.get("reason") == "fallback_failed"
            accepted_here = outcome.get("origin") == "jev"
            item_cost = cost(outcome, rates["jev"] if rates else None)
            if used_fallback:
                item_cost = add_cost(
                    item_cost,
                    cost({"usage": outcome.get("fallback_usage") or {}}, rates["llm"] if rates else None),
                )
        else:
            outcome = row[strategy]
            used_fallback = False
            accepted_here = strategy == "jev" and outcome["status"] == "ok"
            item_cost = cost(outcome, rates[strategy] if rates else None)
        success = outcome["status"] == "ok" and outcome["label"] == row["truth"]
        correct += success
        failures += outcome["status"] != "ok"
        accepted += accepted_here
        accepted_errors += accepted_here and not success
        fallback += used_fallback
        costs.append(item_cost)
        # No synthesized cascade latency is presented as an observed percentile.
        if not cascade:
            latencies.append(outcome["elapsed_ms"])
        group = per_class.setdefault(row["truth"], {"count": 0, "correct": 0})
        group["count"] += 1
        group["correct"] += success
    n = len(rows)
    known = [c for c in costs if c is not None]
    return {
        "strategy": strategy,
        "threshold": threshold,
        "count": n,
        "correct": correct,
        "accuracy": correct / n,
        "accuracy_wilson_95": wilson(correct, n),
        "request_failure_rate": failures / n,
        "jev_acceptance_rate": accepted / n,
        "accepted_error_rate": accepted_errors / accepted if accepted else None,
        "fallback_rate": fallback / n,
        "cost_coverage": len(known) / n,
        "known_cost_subtotal_usd": sum(known),
        "total_cost_usd": sum(known) if len(known) == n else None,
        "cost_per_1000_usd": sum(known) / n * 1000 if len(known) == n else None,
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "latency_basis": "not_measured" if cascade else "observed_wall_clock",
        "per_class": per_class,
    }


def load_run(directory):
    directory = Path(directory)
    if (directory / ".running").exists():
        raise ValueError("Collector is still active")
    run = read_json(directory / "run.json")
    rows = read_records(directory / "results.jsonl")
    ids = [row["id"] for row in rows]
    if not run.get("complete") or len(ids) != len(set(ids)) or set(ids) != set(run["sample_ids"]) or not rows:
        raise ValueError("Run incomplete or result IDs invalid; resume collection before analysis")
    if digest(run["dataset"]) != run["config"]["dataset_hash"]:
        raise ValueError("Run dataset manifest mismatch")
    return run, rows


def analyze(
    run_dir, output, prices_path=None, policy_path=None, thresholds=DEFAULT_THRESHOLDS, max_drop=0.01
):
    run, rows = load_run(run_dir)
    config = run["config"]
    if not math.isfinite(max_drop) or not 0 <= max_drop <= 1:
        raise ValueError("max-drop must be a fraction between 0 and 1")
    thresholds = sorted(set(thresholds))
    if not thresholds or any(not math.isfinite(t) or not 0 <= t <= 1 for t in thresholds):
        raise ValueError("Thresholds must be finite values between 0 and 1")
    policy = read_json(policy_path) if policy_path else None
    if policy:
        check_policy(policy, config)
    if config["split"] == "test" and not policy:
        raise ValueError("Test reporting requires --policy selected on development data")
    if config["mode"] == "cascade-live" and (not policy or config["policy_hash"] != digest(policy)):
        raise ValueError("Live reporting requires the exact policy used for collection")
    prices = read_json(prices_path) if prices_path else (policy.get("prices") if policy else None)
    if policy and prices != policy.get("prices"):
        raise ValueError("Prices must match the frozen policy; create a separate experiment to change prices")
    validate_prices(prices, config)
    if config["mode"] == "cascade-live":
        summaries = [summarize(rows, "cascade-live", prices, policy["threshold"])]
        experiment_cost = summaries[0]["total_cost_usd"]
        selected = policy
        selection_status = "frozen policy; live chain measurement"
    else:
        baseline, jev = summarize(rows, "llm", prices), summarize(rows, "jev", prices)
        evaluated = [policy["threshold"]] if policy else thresholds
        cascades = [summarize(rows, "cascade-replay", prices, t) for t in evaluated]
        summaries = [baseline, jev, *cascades]
        for result in summaries:
            base_cost, result_cost = baseline["total_cost_usd"], result["total_cost_usd"]
            result["savings_vs_llm"] = (
                (1 - result_cost / base_cost) if base_cost and result_cost is not None else None
            )
            result["accuracy_delta_vs_llm"] = result["accuracy"] - baseline["accuracy"]
        experiment_cost = add_cost(baseline["total_cost_usd"], jev["total_cost_usd"])
        selected = policy
        selection_status = "frozen policy evaluation" if policy else "exploratory; no policy selected"
        if not policy and config["split"] == "dev":
            eligible = [
                r
                for r in cascades
                if r["accuracy"] >= baseline["accuracy"] - max_drop and r["total_cost_usd"] is not None
            ]
            if baseline["total_cost_usd"] is not None and eligible:
                best = min(eligible, key=lambda r: (r["total_cost_usd"], -r["accuracy"], -r["threshold"]))
                selected = {
                    "schema_version": 1,
                    "selection_split": "dev",
                    "threshold": best["threshold"],
                    "max_accuracy_drop": max_drop,
                    "config": config,
                    "prices": prices,
                    "dev_results_hash": digest(rows),
                    "dev_sample_ids": run["sample_ids"],
                }
                selection_status = "selected on dev; requires held-out validation"
            else:
                selection_status = "no eligible fully priced candidate; no policy written"
    errors = []
    for row in rows:
        for strategy in ("cascade",) if config["mode"] == "cascade-live" else ("jev", "llm"):
            result = row[strategy]
            if result["status"] != "ok" or result["label"] != row["truth"]:
                errors.append(
                    {
                        "id": row["id"],
                        "truth": row["truth"],
                        "strategy": strategy,
                        "predicted": result["label"],
                        "confidence": result.get("confidence"),
                        "status": result["status"],
                    }
                )
    report = {
        "schema_version": 1,
        "synthetic": config["synthetic"],
        "run": run,
        "selection_status": selection_status,
        "selected_threshold": selected["threshold"] if selected else None,
        "prices": prices,
        "experiment_collection_cost_usd": experiment_cost,
        "summaries": summaries,
        "errors": errors,
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "report.json", report)
    write_json(output / "errors.json", errors)
    if selected:
        write_json(output / "policy.json", selected)
    columns = [k for k in summaries[0] if k not in ("per_class", "accuracy_wilson_95")]
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows({k: row[k] for k in columns} for row in summaries)
    (output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report):
    def number(value, percentage=False):
        if value is None:
            return "unknown / not measured"
        return f"{value * 100:.2f}%" if percentage else f"{value:.4f}"

    config = report["run"]["config"]
    lines = [
        "# " + ("SYNTHETIC DEMO — NOT MODEL PERFORMANCE" if report["synthetic"] else "BANKING77 benchmark"),
        "",
        f"Split: **{config['split']}**. Mode: **{config['mode']}**.",
        f"Models: Jev `{config['jev_model']}`; LLM `{config['model']}`.",
        f"Collection started: {report['run']['started_at']}.",
        "",
        f"Selection: {report['selection_status']}.",
        "",
        "| Strategy | Threshold | Accuracy | Failures | Jev accepted | Accepted error | Fallback | USD / 1k | Cost coverage | P50 ms | P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["summaries"]:
        cells = [row["strategy"], str(row["threshold"]) if row["threshold"] is not None else "—"]
        cells += [
            number(row[k], True)
            for k in (
                "accuracy",
                "request_failure_rate",
                "jev_acceptance_rate",
                "accepted_error_rate",
                "fallback_rate",
            )
        ]
        cells += [
            number(row["cost_per_1000_usd"]),
            number(row["cost_coverage"], True),
            number(row["p50_ms"]),
            number(row["p95_ms"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    frozen = next(
        (
            r
            for r in report["summaries"]
            if r["strategy"] == "cascade-replay" and r["threshold"] == report["selected_threshold"]
        ),
        None,
    )
    if frozen:
        lines += [
            "",
            f"Frozen threshold: **{frozen['threshold']}**. Estimated savings vs LLM: "
            f"**{number(frozen.get('savings_vs_llm'), True)}**. Accuracy change: "
            f"**{frozen['accuracy_delta_vs_llm'] * 100:+.2f} percentage points**.",
        ]
    lines += [
        "",
        "## Interpretation",
        "",
        "- Failures remain in the accuracy denominator. Fallback can also be wrong.",
        "- Cascade replay cost is a counterfactual estimate using paired calls, not the experiment bill.",
        "- Cascade replay has no measured P50/P95. Use a separate live cascade run for wall-clock latency.",
        "- Costs use the supplied USD/token tariffs; cached-input discounts and provider billing adjustments are not modeled.",
        "- Unknown token usage or tariffs stays unknown; known-cost subtotals are not full totals.",
        "- Accuracy Wilson intervals and per-class counts are in report.json; small differences are not proof of equivalence.",
        "- Public benchmark performance does not establish private workload or full-agent task performance.",
        "- jev-latest is a moving alias. Run dates are recorded; exact future reproduction is not guaranteed.",
        "- Requests are sequential, with connection reuse and alternating paired order; timing is environment-dependent.",
        "",
        f"Collection cost at supplied tariffs: {number(report['experiment_collection_cost_usd'])} USD.",
        "",
        "## Error examples (first 10)",
        "",
        "Full error list: errors.json. Sample text stays in the local dataset files.",
        "",
    ]
    for row in report["errors"][:10]:
        lines.append(
            f"- `{row['id']}` / {row['strategy']}: expected `{row['truth']}`, got `{row['predicted']}`; confidence={row['confidence']}, status={row['status']}."
        )
    lines += [
        "",
        "## Reproduction",
        "",
        "Run settings, dataset hashes, model, timestamps and pricing are embedded in report.json.",
        "Data: https://github.com/PolyAI-LDN/task-specific-datasets (CC-BY-4.0).",
        "Cite Casanueva et al., Efficient Intent Detection with Dual Sentence Encoders (2020): https://arxiv.org/abs/2003.04807.",
        "",
    ]
    return "\n".join(lines)
