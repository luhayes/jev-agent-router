import copy
import json

import httpx
import pytest

from jev_agent_router.benchmark.controls import random_control
from jev_agent_router.benchmark.data import digest, read_json, write_json
from jev_agent_router.benchmark.report import analyze, summarize
from jev_agent_router.benchmark.runner import collect, policy_strategy
from jev_agent_router.llm import provider_config


def outcome(label="a", confidence=.9, status="ok"):
    return {
        "label": label, "confidence": confidence, "status": status, "elapsed_ms": 10,
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


def row(i, jev=None, llm=None):
    return {"id": f"dev:{i}", "truth": "a", "jev": jev or outcome(), "llm": llm or outcome()}


def fixture_run(tmp_path, rows):
    dataset = tmp_path / "data"
    dataset.mkdir()
    samples = [{"id": r["id"], "text": r["id"], "label": r["truth"]} for r in rows]
    manifest = {
        "synthetic": True, "criteria": {"a": "A", "b": "B"}, "instructions": "Classify",
        "splits": {"dev": {"count": len(rows), "sha256": digest(samples)}},
    }
    write_json(dataset / "manifest.json", manifest)
    write_json(dataset / "dev.json", samples)
    run = tmp_path / "paired"
    run.mkdir()
    config = {
        "dataset_hash": digest(manifest), "model": "fixture", "jev_model": "jev-latest",
        "timeout": 30, "synthetic": True, "sdk_version": "0.1.0", "llm": provider_config(),
        "diagnostics_version": 1, "jev_probability_sum_tolerance": .01, "mode": "paired", "split": "dev",
    }
    write_json(run / "run.json", {
        "config": config, "dataset": manifest, "complete": True,
        "sample_ids": [r["id"] for r in rows], "started_at": "synthetic",
    })
    (run / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    prices = tmp_path / "prices.json"
    write_json(prices, {
        "as_of": "2026-01-01", "source": "Synthetic test rates",
        "jev": {"model": "jev-latest", "input_per_million": .1, "output_per_million": 0},
        "llm": {"model": "fixture", "input_per_million": 1, "output_per_million": 0},
    })
    return dataset, run, prices


@pytest.mark.parametrize("strategy", ["jev-only", "llm-only", "cascade"])
async def test_select_and_execute_each_strategy(tmp_path, strategy):
    rows = [row(i) for i in range(4)]
    if strategy == "llm-only":
        for r in rows:
            r["jev"] = outcome("b", .99)
    elif strategy == "cascade":
        rows[0]["jev"] = outcome("b", .2)
    dataset, run, prices = fixture_run(tmp_path, rows)
    report = analyze(run, tmp_path / "dev-report", prices_path=prices)
    assert report["selected_strategy"] == strategy
    policy_path = tmp_path / "dev-report/policy.json"
    policy = read_json(policy_path)
    assert policy["schema_version"] == 2
    assert (policy["threshold"] is None) == (strategy != "cascade")
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.typesafe.ai":
            index = int(json.loads(request.content)["state"].split(":")[1])
            recorded = rows[index]["jev"]
            return httpx.Response(200, json={
                "answers": {"route": {"type": "choice", "choice": recorded["label"],
                    "confidence": recorded["confidence"], "probabilities": {"a": .5, "b": .5}}},
                "usage": {"input_tokens": 100, "output_tokens": 0},
            })
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"label":"a"}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 0},
        })

    await collect(dataset, "dev", tmp_path / "live", "fixture", policy_path=policy_path,
                  transport=httpx.MockTransport(handler))
    live = analyze(tmp_path / "live", tmp_path / "live-report", policy_path=policy_path)
    assert live["selected_strategy"] == strategy
    assert live["summaries"][0]["accuracy"] == 1
    assert live["random_controls"] == []
    if strategy == "jev-only":
        assert calls == ["api.typesafe.ai"] * 4
    elif strategy == "llm-only":
        assert calls == ["api.openai.com"] * 4
    else:
        assert calls.count("api.typesafe.ai") == 4 and calls.count("api.openai.com") == 1


def test_test_report_freezes_single_policy_and_diagnostic_threshold(tmp_path):
    dataset, run, prices = fixture_run(tmp_path, [row(i) for i in range(4)])
    analyze(run, tmp_path / "dev", prices_path=prices, thresholds=[.5, .8])
    policy_path = tmp_path / "dev/policy.json"
    policy = read_json(policy_path)
    assert policy["strategy"] == "jev-only"
    assert policy["diagnostic_cascade_threshold"] == .8
    metadata = read_json(run / "run.json")
    metadata["config"]["split"] = "test"
    write_json(run / "run.json", metadata)
    # A hostile test result would favor LLM-only, but cannot change the dev selection.
    (run / "results.jsonl").write_text("".join(json.dumps(row(i, outcome("b"))) + "\n" for i in range(4)))
    report = analyze(run, tmp_path / "test", policy_path=policy_path, thresholds=[.1, .2, .3])
    assert report["selected_strategy"] == "jev-only"
    assert report["selected_threshold"] is None
    assert [r["threshold"] for r in report["random_controls"]] == [.8]
    assert read_json(tmp_path / "test/policy.json") == policy
    markdown = (tmp_path / "test/report.md").read_text()
    assert "Frozen strategy: **jev-only**" in markdown
    assert "Diagnostic comparison only" in markdown


def test_unknown_cost_excludes_only_affected_candidates(tmp_path):
    rows = [row(i) for i in range(4)]
    rows[0]["llm"]["usage"] = {}
    _, run, prices = fixture_run(tmp_path, rows)
    report = analyze(run, tmp_path / "report", prices_path=prices)
    assert report["selected_strategy"] == "jev-only"
    assert report["summaries"][0]["total_cost_usd"] is None
    assert report["summaries"][1]["savings_vs_llm"] is None


def test_random_control_fixes_regressions_and_preserves_error_policy():
    rows = [
        row(0, outcome("b", .1)),                    # chosen correction
        row(1, outcome("a", .1), outcome("b")),      # chosen regression
        row(2, outcome("b", .9)),                    # random candidate, not chosen
        row(3, outcome(None, None, "recoverable_error")),  # mandatory correction
        row(4, outcome(None, None, "request_error")),      # never falls back
    ]
    report = random_control(rows, .5)
    assert report == random_control(list(reversed(rows)), .5)
    assert report["fallback_count"] == 3
    assert report["forced_fallback_count"] == 1
    assert report["randomized_fallback_count"] == 2
    assert (report["corrections"], report["regressions"]) == (2, 1)
    assert report["random_expected_net_gain"] == pytest.approx(1 + 2/3)
    assert report["random_net_gain_central_95"] == [1, 3]
    assert .6 < report["random_fraction_ge_observed"] <= 1
    assert report["cascade_correct"] == summarize(rows, "cascade-replay", threshold=.5)["correct"]


@pytest.mark.parametrize("threshold", [0, 1])
def test_random_control_zero_or_all_fallback_and_failed_llm(threshold):
    rows = [row(0, outcome("b", .5)), row(1, outcome("a", .5), outcome(None, None, "fallback_failed"))]
    report = random_control(rows, threshold)
    assert report["fallback_count"] == int(threshold) * 2
    assert report["net_correct_gain"] == 0
    assert report["random_net_gain_central_95"] == [0, 0]
    assert report["random_fraction_ge_observed"] == 1


@pytest.mark.parametrize("bad", [
    {"schema_version": 2},
    {"schema_version": 2, "strategy": "unknown", "threshold": None},
    {"schema_version": 2, "strategy": "jev-only", "threshold": .5},
    {"schema_version": 2, "strategy": "cascade", "threshold": None},
    {"schema_version": 2, "strategy": "cascade", "threshold": .5, "diagnostic_cascade_threshold": .8},
    {"schema_version": 2, "strategy": "jev-only", "threshold": None, "diagnostic_cascade_threshold": True},
    {"schema_version": 3, "threshold": .5},
])
def test_invalid_frozen_strategy_rejected(bad):
    with pytest.raises(ValueError):
        policy_strategy(bad)


def test_legacy_cascade_policy_still_reports(tmp_path):
    dataset, run, prices = fixture_run(tmp_path, [row(0)])
    analyze(run, tmp_path / "dev", prices_path=prices)
    policy = copy.deepcopy(read_json(tmp_path / "dev/policy.json"))
    policy["schema_version"] = 1
    policy.pop("strategy")
    policy.pop("diagnostic_cascade_threshold")
    policy["threshold"] = .5
    path = tmp_path / "legacy.json"
    write_json(path, policy)
    report = analyze(run, tmp_path / "legacy-report", policy_path=path)
    assert report["selected_strategy"] == "cascade"
    assert report["selected_threshold"] == .5
