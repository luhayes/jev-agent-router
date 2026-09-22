import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

import httpx
import pytest
import yaml

from jev_agent_router.llm import PROVIDERS, provider_config
from jev_agent_router.benchmark.data import digest, read_json, write_json
from jev_agent_router.benchmark.runner import collect as real_collect

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "banking77_actions", ROOT / "benchmarks/banking77/run_actions.py"
)
actions = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = actions
SPEC.loader.exec_module(actions)


def prices():
    return {
        "as_of": "2026-09-22",
        "source": "Synthetic test rates, not provider prices",
        "jev": {"model": "jev-latest", "input_per_million": 0.1, "output_per_million": 0},
        "llm": {"model": "synthetic-model", "input_per_million": 1, "output_per_million": 2},
    }


def env(mode="small"):
    return {
        "BENCHMARK_MODE": mode,
        "BENCHMARK_MODEL": "synthetic-model",
        "BENCHMARK_CONFIRM_PAID": "true",
        "BENCHMARK_PRICES_JSON": json.dumps(prices()),
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"BENCHMARK_CONFIRM_PAID": "false"},
        {"BENCHMARK_MODEL": "$(echo hacked)"},
        {"BENCHMARK_MODEL": "model\ninjected"},
        {"BENCHMARK_PRICES_JSON": ""},
        {"BENCHMARK_PRICES_JSON": '{"api_key": "DO_NOT_PRINT"}'},
        {"BENCHMARK_MODE": "unknown"},
        {"BENCHMARK_PROVIDER": "unknown"},
        {"BENCHMARK_RESPONSE_FORMAT": "text"},
    ],
)
def test_invalid_paid_inputs_rejected_before_calls(changes):
    with pytest.raises(ValueError) as exc:
        actions.settings_from_env(env() | changes)
    assert "DO_NOT_PRINT" not in str(exc.value)


def test_demo_needs_no_model_prices_confirmation_or_keys():
    settings = actions.settings_from_env({"BENCHMARK_PRICES_JSON": "malformed"})
    assert settings == actions.Settings("demo", "", None, False)
    smoke = actions.settings_from_env(env("smoke") | {"BENCHMARK_PRICES_JSON": ""})
    assert smoke.prices is None
    with pytest.raises(ValueError, match="measure_live"):
        actions.settings_from_env(env("smoke") | {"BENCHMARK_MEASURE_LIVE": "true"})


def test_unknown_or_mismatched_prices_rejected():
    p = prices()
    p["llm"]["input_per_million"] = None
    with pytest.raises(ValueError, match="complete verified"):
        actions.settings_from_env(env() | {"BENCHMARK_PRICES_JSON": json.dumps(p)})
    p["llm"]["model"] = "other-model"
    with pytest.raises(ValueError, match="Invalid prices_json"):
        actions.settings_from_env(env() | {"BENCHMARK_PRICES_JSON": json.dumps(p)})


def test_missing_keys_does_not_create_output(tmp_path, monkeypatch):
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="Actions secrets"):
        actions.run(actions.settings_from_env(env()), tmp_path / "results")
    assert not (tmp_path / "results").exists()


def test_workflow_manual_trigger_secret_scope_and_artifact_allowlist():
    workflow = yaml.load((ROOT / ".github/workflows/banking77.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["default"] == "demo"
    assert workflow["on"]["workflow_dispatch"]["inputs"]["confirm_paid"]["default"] == "false"
    assert set(workflow["on"]["workflow_dispatch"]["inputs"]["provider"]["options"]) == set(PROVIDERS)
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    steps = workflow["jobs"]["benchmark"]["steps"]
    secret_steps = [s for s in steps if "secrets." in json.dumps(s)]
    assert len(secret_steps) == 1
    assert secret_steps[0]["if"] == "inputs.mode != 'demo'"
    assert set(secret_steps[0]["env"]) >= {"TYPESAFE_API_KEY", "OPENAI_API_KEY"}
    for provider, (_, key, _) in PROVIDERS.items():
        expression = secret_steps[0]["env"][key]
        assert f"inputs.provider == '{provider}'" in expression
        assert f"secrets.{key}" in expression and "|| ''" in expression
    assert '"refs/heads/$DEFAULT_BRANCH"' in steps[0]["run"]
    for step in steps:
        assert "${{ inputs." not in step.get("run", "")
        if "uses" in step:
            assert re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"])
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    upload = steps[-1]
    assert upload["if"] == "always()"
    assert upload["with"]["include-hidden-files"] == "false"
    paths = upload["with"]["path"].splitlines()
    assert all(p.startswith("benchmark-results/actions/") for p in paths)
    assert all(
        Path(p).name
        in {
            "status.json",
            "provenance.json",
            "prices.json",
            "manifest.json",
            "smoke.json",
            "dev.json",
            "test.json",
            "run.json",
            "results.jsonl",
            "report.md",
            "report.json",
            "metrics.csv",
            "errors.json",
            "policy.json",
        }
        for p in paths
    )


@pytest.mark.parametrize(
    "failure,expected,splits",
    [
        (None, "completed_benchmark", ["smoke", "dev", "test", "test"]),
        ("smoke", "stopped_smoke_failures", ["smoke"]),
        ("policy", "stopped_no_policy", ["smoke", "dev"]),
    ],
)
@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_pipeline_uses_real_collector_and_stops_before_extra_calls(
    tmp_path, monkeypatch, capsys, failure, expected, splits, provider
):
    calls, collected = [], []
    criteria = {"billing": "Billing", "technical": "Technical"}

    def prepare(directory, **kwargs):
        directory.mkdir()
        sets = {
            s: [{"id": f"{s}:{i}", "text": f"{s} sample {i}", "label": "billing"} for i in range(4)]
            for s in ("smoke", "dev", "test")
        }
        manifest = {
            "schema_version": 1,
            "synthetic": True,
            "criteria": criteria,
            "instructions": "Classify.",
            "splits": {s: {"count": len(rows), "sha256": digest(rows)} for s, rows in sets.items()},
        }
        write_json(directory / "manifest.json", manifest)
        for s, rows in sets.items():
            write_json(directory / f"{s}.json", rows)

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.typesafe.ai":
            state = json.loads(request.content)["state"]
            if failure == "smoke":
                return httpx.Response(401)
            wrong = failure == "policy" or state.endswith("0")
            label = "technical" if wrong else "billing"
            confidence = 0.99 if failure == "policy" or not wrong else 0.6
            return httpx.Response(
                200,
                json={
                    "answers": {
                        "route": {
                            "type": "choice",
                            "choice": label,
                            "confidence": confidence,
                            "probabilities": {
                                "billing": 0.2 if wrong else 0.8,
                                "technical": 0.8 if wrong else 0.2,
                            },
                        }
                    },
                    "usage": {"input_tokens": 20, "output_tokens": 0},
                },
            )
        assert str(request.url) == PROVIDERS[provider][0] + "/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"label":"billing"}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    async def collect(*args, **kwargs):
        collected.append(args[1])
        return await real_collect(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(actions, "prepare", prepare)
    monkeypatch.setattr(actions, "collect", collect)
    for _, key, _ in PROVIDERS.values():
        monkeypatch.delenv(key, raising=False)
    for key in ("TYPESAFE_API_KEY", PROVIDERS[provider][1], "JEVCALC_API_KEY"):
        monkeypatch.setenv(key, "SECRET_SENTINEL_DO_NOT_UPLOAD")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    settings = actions.settings_from_env(
        env("standard") | {"BENCHMARK_MEASURE_LIVE": "true", "BENCHMARK_PROVIDER": provider}
    )
    output = tmp_path / "results"
    assert actions.run(settings, output) == (0 if failure is None else 2)
    assert read_json(output / "status.json")["status"] == expected
    status = read_json(output / "status.json")
    assert status["requested_mode"] == "standard"
    assert status["complete"] == (failure is None)
    assert status["completed_report_stages"] == (
        ["smoke", "dev", "test", "live"]
        if failure is None
        else ["smoke"]
        if failure == "smoke"
        else ["smoke", "dev"]
    )
    summary_text = (tmp_path / "summary.md").read_text()
    assert summary_text.startswith(
        "# Requested mode: standard — " + ("COMPLETED" if failure is None else "INCOMPLETE")
    )
    logs = capsys.readouterr().out
    if failure == "smoke":
        assert "Smoke failures: jev=4" in logs
        assert "diagnostic=http_error; HTTP=401" in logs
        assert "::error::Evaluation stopped" in logs
    assert collected == splits
    assert read_json(output / "smoke-run/run.json")["config"]["llm"] == provider_config(provider)
    assert f"LLM service: `{provider}`" in (output / "smoke-report/report.md").read_text()
    assert len(calls) == (29 if failure is None else 8 if failure == "smoke" else 16)
    for file in tmp_path.rglob("*"):
        if file.is_file():
            assert "SECRET_SENTINEL_DO_NOT_UPLOAD" not in file.read_text()
    assert not list(output.rglob(".running"))


def test_demo_runs_without_network_and_creates_summary(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    output = tmp_path / "results"
    assert actions.run(actions.settings_from_env({}), output) == 0
    assert read_json(output / "status.json")["status"] == "completed_demo"
    assert "SYNTHETIC DEMO" in (tmp_path / "summary.md").read_text()


def test_timeout_writes_failure_status_for_recovery(tmp_path, monkeypatch):
    async def stalled(settings, root):
        await asyncio.sleep(1)

    monkeypatch.setattr(actions, "execute", stalled)
    monkeypatch.setattr(actions, "RUN_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        actions.run(actions.settings_from_env({}), tmp_path / "results")
    assert read_json(tmp_path / "results/status.json")["status"] == "failed"
