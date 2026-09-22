# Run BANKING77 on GitHub Actions

The **BANKING77 benchmark** workflow runs on GitHub-hosted Ubuntu with Python 3.12.
It is **manual-only**, defaults to the offline demo, and accepts runs from the
repository's default branch. Pushes, pull requests and schedules do not start it.

## First run: no API keys required

1. Open the repository's **Actions** tab.
2. Select **BANKING77 benchmark**, then **Run workflow**.
3. Select the default branch (`main` in this repository).
4. Keep `mode=demo` and the other defaults, then click **Run workflow**.
5. Open the completed run. Its **Summary** shows the synthetic reports. Download
   the `banking77-demo-...` attachment under **Artifacts** for the report files.

Demo uses synthetic responses and fictional prices. It makes no provider calls
and does not receive repository API secrets.

## Add keys for live evaluation

In the repository, open **Settings → Secrets and variables → Actions → New
repository secret**, and add:

| Secret name | Value |
|---|---|
| `TYPESAFE_API_KEY` | Your TypeSafe API key |
| `OPENAI_API_KEY` | Your OpenAI API key |

Store keys only in Secrets. **Never paste a key into a dispatch input, pricing
JSON, source file or issue.** Dispatch settings, logs, summaries and artifacts
in this public repository should be treated as public.

The workflow supplies secrets only to the paid collection step. Installation,
input validation, demo and artifact upload do not receive them. There are no
`pull_request` or `pull_request_target` triggers, checkout does not persist its
Git credentials, the workflow token has only `contents: read`, and external
actions are pinned to full commit SHAs. No `.env`, environment dump or raw
provider response is uploaded. Benchmark telemetry stays disabled.

These controls do not make secrets inaccessible to trusted repository writers:
someone allowed to change and run workflows can modify code to misuse them.
Restrict write access accordingly. GitHub log masking is an additional defense,
not a reason to print secrets.

## Choose a run mode

| Mode | Smoke / development / test samples | Paired provider calls | Pricing required? |
|---|---:|---:|---|
| `demo` | Synthetic fixture | 0 | No |
| `smoke` | 20 / 0 / 0 | 40 | Optional |
| `small` | 20 / 154 / 154 | 656 | Yes |
| `standard` | 20 / 385 / 770 | 2,350 | Yes |
| `full-test` | 20 / 385 / 3,074 | 6,958 | Yes |

All live modes require a `model` supporting strict JSON schema on OpenAI Chat
Completions, both secrets, and **confirm_paid=true**. Start with `smoke` before
increasing volume. The small split is exploratory and is not sufficient to
establish close accuracy equivalence.

`measure_live=true` is available for `small`, `standard` and `full-test`. It adds
one Jev call per test sample and an LLM call for each request needing fallback
(at most twice the test sample count). It measures the actual Router chain after
the paired test evaluation. Leave it off for the first run.

Call counts exclude reruns and interrupted samples. Model token charges still
apply when running in Actions. The workflow does not enforce a dollar budget;
use provider budget controls where available. It runs sequentially, and only one
benchmark workflow runs at a time. Starting another run does not cancel an
ongoing paid run.

## Enter prices

For `small`, `standard` or `full-test`, copy the JSON structure from
[`prices.example.json`](prices.example.json), replace every `null` with a verified
USD rate per million tokens, set the exact LLM model ID, and enter the result in
`prices_json`. It may be pasted as a single line. Set `as_of` to the date you
checked the prices and `source` to the provider pricing URLs/assumptions.

- `jev.model` must be `jev-latest`.
- `llm.model` must exactly match the workflow's `model` input.
- Use `0` only for a verified zero tariff.
- Missing, malformed, negative or incomplete rates stop validation before paid
  calls in benchmark modes.
- Smoke may omit pricing; its cost columns will then remain unknown.
- Do not enter secrets into this field. Prices and model names are report data.

Actual token usage still may be unavailable for failed calls; a complete tariff
file does not manufacture missing usage. Cached-token discounts and other
billing adjustments are not modeled by this benchmark.

## Execution and stopping behavior

Live runs prepare the pinned public BANKING77 dataset and then run smoke first.
If smoke records any provider failure, larger stages stop. Otherwise benchmark
modes collect development data, select a threshold, freeze the policy, and
collect/evaluate test data. If no eligible fully priced threshold is selected,
test and live calls are skipped. This is a valid experimental outcome, not a
workflow crash; the summary and `status.json` make the stop explicit.

A selected policy satisfies the configured development accuracy margin (the
existing default of one percentage point). **It is not guaranteed to save
money.** Check the report's estimated savings and held-out quality before
adopting it. Test reporting does not tune thresholds again.

Synthetic results are labeled throughout. Paired replay has no measured cascade
P50/P95; actual cascade timings appear only in the optional live measurement.

## Reports and interrupted runs

The workflow publishes Markdown reports in its run summary and uploads an
allowlist of files beneath `benchmark-results/actions/`:

- Public dataset splits and manifest, for reproducibility and local recovery.
- `run.json` and `results.jsonl` for completed samples.
- Reports, metrics, errors and the selected policy when available.
- Verified pricing, workflow/commit provenance and `status.json`.

Artifacts are retained for **14 days** (subject to repository policy). Download
results you want to retain for a blog post. Artifacts are uploaded even when an
earlier step fails if the runner is still able to execute the upload step. A
forced cancellation or runner loss can prevent upload.

A cooperative 300-minute deadline leaves time before the 330-minute job limit
for cleanup/upload. Long runs may stop before finishing. An Actions rerun starts
from scratch and can incur charges again; it does **not** automatically restore
a previous artifact. To continue locally:

1. Download/extract the artifact and preserve the relative dataset/run folders.
2. Check out the commit recorded in `provenance.json` and install the project.
3. Supply keys locally and run the matching `collect --resume` command from the
   [benchmark walkthrough](README.md), preserving model, timeout, dataset and
   policy. Use the actual extracted paths.
4. If a `.running` lock exists after a hard kill, remove it only after confirming
   no collector is active. Hidden lock files are not uploaded by the workflow.

The artifact is intended for this fixed **public** dataset. This workflow does
not accept uploaded private workloads and never automatically commits results
or publishes them to the JevCalc blog.

## Implementation

- Workflow: [`.github/workflows/banking77.yml`](../../.github/workflows/banking77.yml).
- Orchestration: [`run_actions.py`](run_actions.py).
- Existing local benchmark: [walkthrough](README.md).

The orchestration validates inputs before paid work, passes values as environment
variables instead of interpolating them into shell code, and reuses the same
collector, analyzer and frozen-policy format as local runs.
