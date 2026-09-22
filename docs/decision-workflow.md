# Evaluate, freeze and run a model decision policy

Use `jev-agent-router` for two distinct jobs: **offline policy evaluation** and
**validated runtime routing**. The evaluator can recommend Jev-only, LLM-only,
or a cascade. The core `Router` handles Jev-first execution; the application
example below also dispatches the LLM-only strategy. Nothing executes a tool.

JevCalc publishes experiments and provides a cost calculator and optional
telemetry console. A JevCalc account is not required to use this workflow or SDK.

## 1. Verify the machinery without API keys

From a checkout of this repository, with Python 3.11+:

```bash
python -m pip install -e '.[dev]'
python -m jev_agent_router.benchmark demo --output benchmark-results/demo
python -m jev_agent_router.benchmark faults --output benchmark-results/faults
```

Windows: create a Python 3.12 virtual environment with `py -3.12 -m venv .venv`,
then use `.venv\Scripts\python.exe` instead of `python` in the commands.
Use fresh output directories for each run. Demo results are synthetic arithmetic
and parser fixtures, never evidence of model quality. Fault results are behavior
checks. Both commands run without provider calls or analytics upload.

You can also run **Decision validation (offline)** in the repository's Actions
tab, or in your fork. No Secrets required. Reports are attached to the run.

## 2. Define the task and acceptance criteria before testing

Create a bounded label-to-description mapping. Review it against labeled
examples: a label's name may not describe its actual meaning. Version the mapping
and instructions together. Set aside test data before tuning the descriptions.
Split by customer, document, time or another independence unit where appropriate.
Exact-text checks alone cannot detect paraphrases or shared-entity leakage.

Copy [decision-record.example.json](decision-record.example.json) into your local
`benchmark-results/` directory. Set acceptable accuracy, request failure rate,
P95, cost and any critical-class requirements. Null limits are unfinished decisions,
not a pass. This record is a human review template, not an automatic release gate.

The current selector minimizes fully known estimated cost among candidates with
dev accuracy at least `LLM accuracy - max_drop`. It does **not** enforce your
absolute quality, latency, failure-rate or critical-class requirements. Check those
separately before release. No candidate satisfying your needs is a valid outcome.

## 3. Import your labeled data

Use [workload.example.json](workload.example.json) as the input shape. Replace all
examples with enough representative, independently labeled data; its five toy rows
are only a schema illustration. Every dev/test class must have examples. Smoke is
small and checks connectivity/schema, not statistical quality.

```bash
python -m jev_agent_router.benchmark import --source benchmark-results/my-workload.json --output benchmark-results/workload
```

This **offline** command validates labels and schema, rejects repeated IDs or
normalized exact text within/across splits, and writes `manifest.json` plus
`smoke.json`, `dev.json`, `test.json` with integrity hashes. It preserves your
explicit splits and records the criteria version. It does not upload your data.
Keep private input/results out of git and public Actions artifacts. IDs, label
names and descriptions may also be sensitive, even when sample text is omitted.

## 4. Collect paired results, then select only on dev

The following `collect` commands make **paid API calls** and send each sample,
criteria and instructions to the selected providers. Configure `TYPESAFE_API_KEY`
and the appropriate fallback-provider key in your local environment. Analysis is
offline. `--resume` can continue an interrupted collection with identical settings.

Example configuration: Gemini with `GEMINI_API_KEY`; replace `YOUR_MODEL_ID` with
an available exact model ID. Use that same ID and response format throughout.
Copy [the price schema](../benchmarks/banking77/prices.example.json) to
`benchmark-results/prices.json` and verify the rates for your chosen models.
The schema file is not a current price quotation. Do not invent missing usage.

```bash
python -m jev_agent_router.benchmark collect --dataset benchmark-results/workload --split smoke --provider gemini --model YOUR_MODEL_ID --output benchmark-results/smoke-run
python -m jev_agent_router.benchmark analyze --run benchmark-results/smoke-run --output benchmark-results/smoke-report --prices benchmark-results/prices.json
```

Inspect smoke failures and diagnostics before continuing. These individual CLI
commands do not automatically stop the next command for you. The BANKING77
workflow has its own automatic smoke gate.

```bash
python -m jev_agent_router.benchmark collect --dataset benchmark-results/workload --split dev --provider gemini --model YOUR_MODEL_ID --output benchmark-results/dev-run
python -m jev_agent_router.benchmark analyze --run benchmark-results/dev-run --output benchmark-results/dev-report --prices benchmark-results/prices.json --max-drop 0.01
```

Outputs include `report.md`, `report.json`, `metrics.csv`, `errors.json`, and
`random-controls.json`. A `policy.json` is written **only if an eligible, fully
priced candidate exists**. It freezes the selected strategy/threshold, data hash,
provider/model configuration, supplied prices and dev results hash. Retain the
repository commit as well: the package version alone does not pin source changes.

The dev report compares Jev-only, LLM-only and all configured cascade thresholds.
Random controls ask whether confidence gating adds value beyond selecting the
same number of fallback calls randomly. Equal call counts do not imply equal
cost. Random-allocation tail fractions are not proof of generalization.

## 5. Test the frozen choice, then measure it live

Do not tune thresholds after reading the test report. If the result is unsuitable,
revise the experiment and use a fresh untouched test set.

```bash
python -m jev_agent_router.benchmark collect --dataset benchmark-results/workload --split test --provider gemini --model YOUR_MODEL_ID --output benchmark-results/test-run
python -m jev_agent_router.benchmark analyze --run benchmark-results/test-run --policy benchmark-results/dev-report/policy.json --output benchmark-results/test-report
python -m jev_agent_router.benchmark collect --dataset benchmark-results/workload --split test --provider gemini --model YOUR_MODEL_ID --policy benchmark-results/dev-report/policy.json --output benchmark-results/live-run
python -m jev_agent_router.benchmark analyze --run benchmark-results/live-run --policy benchmark-results/dev-report/policy.json --output benchmark-results/live-report
```

The first collection calls both providers per sample for paired comparisons.
The second collection makes additional paid calls to execute only the frozen
strategy, so its wall-clock latency is measured. If Jev-only was selected, it
makes no LLM calls; LLM-only makes no Jev calls. For cascade it calls Jev and
conditionally the fallback. Replay latency is not measured. A diagnostic cascade
in the test report is exploratory when the selected policy is a single model.

Review the decision record: failures stay in accuracy denominators; unknown costs
stay unknown; inspect uncertainty and per-class results, not only aggregate scores.
A frozen policy is an experiment output, not automatic permission to deploy.

## 6. Integrate exactly the evaluated choice

[examples/selected_policy.py](../examples/selected_policy.py) loads the frozen
policy and dataset manifest, verifies their configuration, and calls only the
selected providers. The model/provider come from the evaluated policy, rather
than a new application default. It uses the same instructions and descriptions.

Create `benchmark-results/request.json` containing `{"state":"Where is my invoice?"}`.
From bash, Windows cmd, or another shell supporting input redirection:

```bash
python examples/selected_policy.py --dataset benchmark-results/workload --policy benchmark-results/dev-report/policy.json < benchmark-results/request.json
```

For PowerShell, pipe `Get-Content -Raw benchmark-results/request.json` to the same
Python command instead. This is a **paid** inference example, not an offline demo.
For a server, reuse an `httpx.AsyncClient` and call the example's async `decide`
function; manage its lifecycle in your application. Jev-only uses threshold 0
and no fallback: valid answers are accepted, invalid/transient responses abstain.
Catch errors and choose your own review/rollback behavior. Never silently execute
a selected label as a command or tool.

The core Router provides local response validation, at most one fallback attempt,
cooperative per-stage timeouts, cancellation propagation and sanitized observer
metadata. It does not supply an overall workflow deadline, retries, model-quality
guarantees, authentication recovery or application-specific action authorization.
Add an application deadline if needed and test it separately.

## 7. Check failure behavior and observe real usage

Run the [offline fault experiment](../benchmarks/faults/README.md) before rolling
out integration changes. It explicitly includes high-confidence errors and a
fallback regression. Passing all contracts includes expected errors; it is not
100% successful inference.

Start a limited rollout against your existing evaluated policy, record reason,
origin, latency and available usage, and retain a rollback target. Core local
observers work without a JevCalc account. Optional JevCalc telemetry is a separate
opt-in integration; this evaluation never enables it. Operational telemetry alone
cannot establish accuracy: maintain a labeled review sample and repeat evaluation
when workload, criteria, model aliases or prices change.

The reason to adopt this package is to reuse this tested evaluation/execution
contract instead of rebuilding its checks. The evidence may still tell you that
a single provider is the best policy for your workload.
