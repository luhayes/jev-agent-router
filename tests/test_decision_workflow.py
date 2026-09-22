import copy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from jev_agent_router import __version__, PROBABILITY_SUM_TOLERANCE
from jev_agent_router.benchmark.custom import import_dataset
from jev_agent_router.benchmark.data import digest, load_split, write_json
from jev_agent_router.benchmark.faults import run_experiment
from jev_agent_router.benchmark.report import analyze
from jev_agent_router.benchmark.runner import collect
from jev_agent_router.llm import provider_config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("selected_policy", ROOT / "examples/selected_policy.py")
application = importlib.util.module_from_spec(spec)
spec.loader.exec_module(application)


@pytest.fixture
def payload():
    return json.loads((ROOT / "docs/workload.example.json").read_text())


def save_source(tmp_path, payload):
    path = tmp_path / "source.json"
    write_json(path, payload)
    return path


def test_import_preserves_splits_and_detects_tampering(tmp_path, payload):
    output = tmp_path / "data"
    manifest = import_dataset(save_source(tmp_path, payload), output)
    assert manifest["dataset_kind"] == "custom"
    assert manifest["synthetic"] is False
    for split in ("smoke", "dev", "test"):
        assert load_split(output, split)[1] == payload[split]
    payload["test"][0]["label"] = "technical"
    write_json(output / "test.json", payload["test"])
    with pytest.raises(ValueError, match="manifest"):
        load_split(output, "test")


@pytest.mark.parametrize("problem", ["duplicate_id", "leakage", "unknown_label", "missing_class", "empty", "extra"])
def test_import_rejects_invalid_or_leaked_data_before_writing(tmp_path, payload, problem):
    if problem == "duplicate_id":
        payload["test"][0]["id"] = payload["dev"][0]["id"]
    elif problem == "leakage":
        payload["test"][0]["text"] = "  " + payload["dev"][0]["text"].upper().replace(" ", "  ")
    elif problem == "unknown_label":
        payload["dev"][0]["label"] = "unknown"
    elif problem == "missing_class":
        payload["test"] = payload["test"][:1]
    elif problem == "empty":
        payload["smoke"] = []
    else:
        payload["test"][0]["secret"] = "extra field"
    with pytest.raises(ValueError):
        import_dataset(save_source(tmp_path, payload), tmp_path / "data")
    assert not (tmp_path / "data").exists()


async def test_custom_data_runs_through_selection_and_heldout_report(tmp_path, payload):
    output = tmp_path / "data"
    manifest = import_dataset(save_source(tmp_path, payload), output)
    # Explicitly isolate testing; the public importer never marks real data synthetic.
    manifest["synthetic"] = True
    write_json(output / "manifest.json", manifest)
    truths = {r["text"]: r["label"] for split in ("smoke", "dev", "test") for r in payload[split]}

    def handler(request):
        body = json.loads(request.content)
        if request.url.host == "api.typesafe.ai":
            label = truths[body["state"]]
            return httpx.Response(200, json={"answers": {"route": {
                "type": "choice", "choice": label, "confidence": 0.9,
                "probabilities": {"billing": 0.5, "technical": 0.5},
            }}, "usage": {"input_tokens": 10, "output_tokens": 0}})
        label = truths[json.loads(body["messages"][1]["content"])["state"]]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"label": label}),
        }}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    write_json(tmp_path / "prices.json", {
        "as_of": "2026-09-22", "source": "synthetic test prices",
        "jev": {"model": "jev-latest", "input_per_million": 0.1, "output_per_million": 0},
        "llm": {"model": "test", "input_per_million": 1, "output_per_million": 1},
    })
    for split in ("dev", "test"):
        await collect(output, split, tmp_path / f"{split}-run", "test", transport=httpx.MockTransport(handler))
        report = analyze(tmp_path / f"{split}-run", tmp_path / f"{split}-report",
                         prices_path=tmp_path / "prices.json",
                         policy_path=tmp_path / "dev-report/policy.json" if split == "test" else None)
        assert report["selected_strategy"] == "jev-only"
    text = (tmp_path / "test-report/report.md").read_text()
    assert "user-supplied workload" in text
    assert "PolyAI" not in text


async def test_fault_report_checks_real_calls_and_failure_semantics(tmp_path, monkeypatch):
    # Any accidental real egress fails this test even if it could be caught by Router.
    async def no_network(*args, **kwargs):
        pytest.fail("Fault experiment attempted a real HTTP transport")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    report = await run_experiment(tmp_path / "faults", repeats=1)
    assert report["passed"] and report["checks_total"] == 231
    assert len(report["rows"]) == 33
    rows = {(r["scenario"], r["strategy"]): r for r in report["rows"]}
    assert rows["rate_limit", "cascade"]["correct"]
    assert rows["rate_limit", "jev-only"]["status"] == "abstained"
    assert rows["authentication_error", "cascade"]["calls"]["llm"] == 0
    assert rows["confidently_wrong", "cascade"]["correct"] is False
    assert rows["fallback_can_regress", "jev-only"]["correct"]
    assert not rows["fallback_can_regress", "cascade"]["correct"]
    assert rows["fallback_timeout", "cascade"]["status"] == "fallback_error"
    assert rows["cancel_during_fallback", "cascade"]["status"] == "cancelled"
    assert "not provider reliability" in (tmp_path / "faults/report.md").read_text()


def policy_for(manifest, strategy):
    return {
        "schema_version": 2, "selection_split": "dev", "strategy": strategy,
        "threshold": 0.8 if strategy == "cascade" else None,
        "config": {"dataset_hash": digest(manifest), "model": "test", "jev_model": "jev-latest",
                   "timeout": 1, "synthetic": False, "sdk_version": __version__, "diagnostics_version": 1,
                   "jev_probability_sum_tolerance": PROBABILITY_SUM_TOLERANCE, "llm": provider_config()},
    }


@pytest.mark.parametrize("strategy,hosts", [
    ("jev-only", ["api.typesafe.ai"]), ("llm-only", ["api.openai.com"]),
    ("cascade", ["api.typesafe.ai", "api.openai.com"]),
])
async def test_application_dispatches_only_selected_providers(tmp_path, payload, monkeypatch, strategy, hosts):
    manifest = import_dataset(save_source(tmp_path, payload), tmp_path / "data")
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    if strategy != "llm-only":
        monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    if strategy != "jev-only":
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.typesafe.ai":
            return httpx.Response(200, json={"answers": {"route": {
                "type": "choice", "choice": "billing", "confidence": 0.4,
                "probabilities": {"billing": 0.6, "technical": 0.4},
            }}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"label":"billing"}',
        }}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        policy = policy_for(manifest, strategy)
        result = await application.decide(manifest, policy, "invoice", client=client)
        assert result["strategy"] == strategy
        assert calls == hosts
        calls.clear()
        changed = copy.deepcopy(manifest)
        changed["criteria"]["billing"] = "Different task"
        with pytest.raises(ValueError, match="dataset_hash"):
            await application.decide(changed, policy, "invoice", client=client)
        policy["config"]["sdk_version"] = "different"
        with pytest.raises(ValueError, match="sdk_version"):
            await application.decide(manifest, policy, "invoice", client=client)
        assert calls == []
