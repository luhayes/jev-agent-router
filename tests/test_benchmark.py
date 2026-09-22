import json
import math
import subprocess
import sys

import httpx
import pytest

from jev_agent_router.benchmark.__main__ import demo, main
from jev_agent_router.benchmark.data import digest, load_split, prepare, read_json, write_json
from jev_agent_router.benchmark.report import analyze, cost, replay, summarize
from jev_agent_router.benchmark.runner import collect, read_records


@pytest.fixture
def synthetic_dataset(tmp_path):
    directory = tmp_path / "dataset"
    directory.mkdir()
    rows = [{"id": "dev:0", "text": "Please check my card", "label": "card"}]
    manifest = {
        "schema_version": 1,
        "synthetic": True,
        "criteria": {"card": "Card", "cash": "Cash"},
        "instructions": "Classify the request.",
        "splits": {"dev": {"count": 1, "sha256": digest(rows)}},
    }
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "dev.json", rows)
    return directory


def llm_response(label="card"):
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"label": label})}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5},
        },
    )


def jev_response(confidence=0.5, label="card", probabilities=None):
    return httpx.Response(
        200,
        json={
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": label,
                    "confidence": confidence,
                    "probabilities": probabilities or {"card": 0.8, "cash": 0.2},
                }
            },
            "usage": {"input_tokens": 20, "output_tokens": 0},
        },
    )


@pytest.mark.parametrize(
    "status,expected,fallback",
    [
        (401, "request_error", False),
        (422, "request_error", False),
        (429, "recoverable_error", True),
        (503, "recoverable_error", True),
    ],
)
async def test_replay_preserves_router_http_policy(tmp_path, synthetic_dataset, status, expected, fallback):
    def handler(request):
        return httpx.Response(status) if request.url.host == "api.typesafe.ai" else llm_response()

    output = tmp_path / "run"
    await collect(synthetic_dataset, "dev", output, "synthetic", transport=httpx.MockTransport(handler))
    row = read_records(output / "results.jsonl")[0]
    assert row["jev"]["status"] == expected
    assert replay(row, 0.8)[1] == fallback
    metrics = summarize([row], "cascade-replay", threshold=0.8)
    assert metrics["accuracy"] == int(fallback)
    assert metrics["request_failure_rate"] == int(not fallback)
    assert metrics["total_cost_usd"] is None
    assert metrics["p95_ms"] is None


async def test_confidence_not_max_probability_and_no_label_leak(tmp_path, synthetic_dataset, monkeypatch):
    monkeypatch.setenv("JEVCALC_API_KEY", "must-never-be-uploaded")
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if request.url.host == "api.typesafe.ai":
            assert body["state"] == "Please check my card"
            assert set(body["questions"]["route"]["criteria"]) == {"card", "cash"}
            assert "truth" not in body and "label" not in body
            return jev_response(confidence=0.55)
        assert request.url.host == "api.openai.com"
        payload = json.loads(body["messages"][1]["content"])
        assert payload["state"] == "Please check my card"
        assert set(payload) == {"state", "criteria"}
        return llm_response()

    output = tmp_path / "run"
    transport = httpx.MockTransport(handler)
    await collect(synthetic_dataset, "dev", output, "synthetic", transport=transport)
    row = read_records(output / "results.jsonl")[0]
    assert row["jev"]["confidence"] == 0.55
    assert replay(row, 0.7)[1] is True  # max probability is 0.8; confidence is 0.55
    assert len(requests) == 2
    # Resume never repeats completed paid calls, and changed models are rejected.
    await collect(synthetic_dataset, "dev", output, "synthetic", transport=transport, resume=True)
    assert len(requests) == 2
    with pytest.raises(ValueError, match="configuration differs"):
        await collect(synthetic_dataset, "dev", output, "different", transport=transport, resume=True)
    assert not (output / ".running").exists()


async def test_invalid_response_and_failed_fallback_count_as_failure(tmp_path, synthetic_dataset):
    def handler(request):
        if request.url.host == "api.typesafe.ai":
            return jev_response(probabilities={"card": 0.4, "cash": 0.2})
        return llm_response(label="not-allowed")

    output = tmp_path / "run"
    await collect(synthetic_dataset, "dev", output, "synthetic", transport=httpx.MockTransport(handler))
    row = read_records(output / "results.jsonl")[0]
    metrics = summarize([row], "cascade-replay", threshold=0.8)
    assert metrics["accuracy"] == 0
    assert metrics["fallback_rate"] == 1
    assert metrics["request_failure_rate"] == 1


def test_unknown_cost_not_zero_and_explicit_zero_tariff():
    outcome = {"usage": {"input_tokens": 100, "output_tokens": None}}
    rates = {"input_per_million": 1, "output_per_million": 2}
    assert cost(outcome, rates) is None
    assert cost(outcome, None) is None
    rates["output_per_million"] = 0
    assert cost(outcome, rates) == pytest.approx(0.0001)
    outcome["usage"]["input_tokens"] = None
    assert cost(outcome, rates) is None


def test_prepare_deterministic_and_disjoint(tmp_path):
    source = tmp_path / "csv"
    source.mkdir()
    for split in ("train", "test"):
        text = "text,category\n" + "".join(
            f"{split} request {label} {i},intent_{label}\n" for label in range(77) for i in range(12)
        )
        (source / f"{split}.csv").write_text(text)
    first, second = tmp_path / "first", tmp_path / "second"
    a = prepare(first, source)
    b = prepare(second, source)
    assert a == b
    assert {k: v["count"] for k, v in a["splits"].items()} == {"dev": 385, "test": 770, "smoke": 20}
    samples = {s: load_split(first, s)[1] for s in a["splits"]}
    assert not {r["id"] for r in samples["smoke"]} & {r["id"] for r in samples["dev"]}
    assert len(a["criteria"]) == 77
    write_json(first / "test.json", [])
    with pytest.raises(ValueError, match="manifest"):
        load_split(first, "test")


async def test_full_demo_policy_freeze_live_and_unknown_prices(tmp_path):
    output = tmp_path / "demo"
    await demo(output)
    dev = read_json(output / "dev-report/report.json")
    test = read_json(output / "test-report/report.json")
    live = read_json(output / "live-report/report.json")
    policy = read_json(output / "dev-report/policy.json")
    assert dev["synthetic"] and test["synthetic"] and live["synthetic"]
    assert policy["threshold"] == 0.95  # deterministic tie-break: stricter when costs/accuracy tie
    assert test["selected_threshold"] == policy["threshold"]
    assert len(test["summaries"]) == 3  # cannot re-sweep test thresholds
    assert test["summaries"][-1]["accuracy"] == 1
    assert test["summaries"][-1]["p95_ms"] is None
    assert live["summaries"][0]["accuracy"] == 1
    assert live["summaries"][0]["p95_ms"] >= 0
    assert test["experiment_collection_cost_usd"] > test["summaries"][-1]["total_cost_usd"]
    assert "SYNTHETIC DEMO" in (output / "test-report/report.md").read_text()
    with pytest.raises(ValueError, match="requires --policy"):
        analyze(output / "test-run", output / "invalid")
    unknown = analyze(output / "dev-run", output / "unknown")
    assert unknown["selected_threshold"] is None
    assert not (output / "unknown/policy.json").exists()
    assert all(s["total_cost_usd"] is None for s in unknown["summaries"])
    run_path = output / "test-run/run.json"
    run = read_json(run_path)
    run["config"]["model"] = "changed-model"
    write_json(run_path, run)
    with pytest.raises(ValueError, match="mismatch: model"):
        analyze(output / "test-run", output / "changed", policy_path=output / "dev-report/policy.json")


async def test_interruption_resume_and_incomplete_analysis(tmp_path, synthetic_dataset):
    output = tmp_path / "run"

    def handler(request):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await collect(synthetic_dataset, "dev", output, "synthetic", transport=httpx.MockTransport(handler))
    assert not (output / ".running").exists()
    with pytest.raises(ValueError, match="incomplete"):
        analyze(output, tmp_path / "report")

    def success(request):
        return jev_response() if request.url.host == "api.typesafe.ai" else llm_response()

    await collect(
        synthetic_dataset, "dev", output, "synthetic", transport=httpx.MockTransport(success), resume=True
    )
    assert read_json(output / "run.json")["complete"]


@pytest.mark.parametrize("threshold", [math.nan, math.inf, -1, 1.1])
async def test_reject_invalid_thresholds(tmp_path, synthetic_dataset, threshold):
    def handler(request):
        return jev_response() if request.url.host == "api.typesafe.ai" else llm_response()

    output = tmp_path / "run"
    await collect(synthetic_dataset, "dev", output, "synthetic", transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="Thresholds"):
        analyze(output, tmp_path / "report", thresholds=[threshold])


def test_cli_help_and_bad_command(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "jev_agent_router.benchmark", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "collect" in result.stdout
    assert main(["analyze", "--run", str(tmp_path / "missing"), "--output", str(tmp_path / "out")]) == 2


async def test_no_credentials_no_paid_calls(tmp_path, synthetic_dataset, monkeypatch):
    # Relabel only the synthetic manifest to verify preflight; no requests should run.
    path = synthetic_dataset / "manifest.json"
    data = read_json(path)
    data["synthetic"] = False
    write_json(path, data)
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="Set TYPESAFE_API_KEY"):
        await collect(synthetic_dataset, "dev", output, "model")
    assert not output.exists()
