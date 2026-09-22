# Run BANKING77 on GitHub Actions

The **BANKING77 benchmark** workflow runs on GitHub-hosted Ubuntu with Python 3.12.
It is **manual-only**, defaults to the offline demo, and accepts runs from the
repository's default branch. Pushes, pull requests and schedules do not start it.

New runs use the [versioned English category descriptions](CRITERIA.md), shared
by Jev and the selected LLM. After a description update, start **Run workflow**
on `main` rather than rerunning an old job. Reports show the criteria version;
new descriptions require fresh calls and a newly selected development policy.

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
repository secret**, and add `TYPESAFE_API_KEY` plus the key for your selected
LLM service. **An OpenAI key is not required for other providers.**

| Secret name | Value |
|---|---|
| `TYPESAFE_API_KEY` | Your TypeSafe API key |
| `OPENAI_API_KEY` | OpenAI, only for `provider=openai` |
| `DEEPSEEK_API_KEY` | DeepSeek, only for `provider=deepseek` |
| `OPENROUTER_API_KEY` | OpenRouter, only for `provider=openrouter` |
| `GEMINI_API_KEY` | Google AI Studio / Gemini API, only for `provider=gemini` |
| `MOONSHOT_API_KEY` | Kimi, for `provider=kimi` (international) or `kimi-cn` (China) |

Store keys only in Secrets. **Never paste a key into a dispatch input, pricing
JSON, source file or issue.** Dispatch settings, logs, summaries and artifacts
in this public repository should be treated as public.

The workflow supplies the TypeSafe key and only the selected LLM service key
to the paid collection step. Other LLM secret variables are empty. Installation,
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

All live modes require a `provider`, an exact `model` ID available to your account,
that provider's key plus the TypeSafe key, and **confirm_paid=true**. Start with
`smoke` before increasing volume. Each run tests **one** selected LLM, not every
provider in the dropdown.

Keep `response_format=auto` initially:

| Provider | Default output format | API base URL |
|---|---|---|
| `openai` | `json_schema` | `https://api.openai.com/v1` |
| `deepseek` | `json_object` | `https://api.deepseek.com` |
| `openrouter` | `json_schema` | `https://openrouter.ai/api/v1` |
| `gemini` | `json_schema` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `kimi` | `json_object` | `https://api.moonshot.ai/v1` |
| `kimi-cn` | `json_object` | `https://api.moonshot.cn/v1` |

Use the Kimi endpoint matching the platform that issued your key. The Gemini
preset uses the Gemini Developer API, not Vertex AI authentication. Model IDs
are service-specific: OpenRouter usually uses `publisher/model` IDs. Choose a
model that supports the selected format. OpenRouter requests endpoints that
support the parameters via `require_parameters=true`. JSON mode gets an explicit
output instruction; both modes validate the exact allowed label locally.
Unsupported formats, empty responses, refusals and truncated output count as
failures. The adapter never silently changes formats or retries paid calls.

For example, a first DeepSeek run needs `TYPESAFE_API_KEY` and `DEEPSEEK_API_KEY`:
choose `mode=smoke`, `provider=deepseek`, your account's model ID,
`response_format=auto`, leave `prices_json` empty and `measure_live=false`, and
check `confirm_paid`. Inspect the smoke report before selecting `small`.

Changing provider, model or output format requires a fresh development evaluation
and policy. Reports record the provider, API base URL, resolved format and adapter
version; frozen policies and resume checks reject mismatches. `auto` and an
explicit selection of the same resolved format are equivalent.

The small split is exploratory and is not sufficient to establish close accuracy
equivalence.

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
If smoke records any provider failure, larger stages stop. This includes `standard`:
its first report is always `Split: smoke`, followed by development, test and
optional live reports only after checks pass. An answered-but-wrong classification
does not count as a provider failure.

The log prints per-provider failure counts and sanitized Jev diagnostics:
HTTP status, original Jev reason, an error code, and probability sum when available.
`invalid_probability_sum` identifies a total outside the documented compatibility
range `[0.99, 1.01]` (with `1e-12` for floating-point boundary arithmetic).
All labels must still be present and every probability must be finite and in
`[0, 1]`. Original probabilities are retained; no normalization is performed. Valid usage
returned with an invalid answer is preserved; missing usage remains unknown.
No response bodies, input text, or credentials are added to diagnostics.

The historical paired probe's `fallback_failed` meant its intentional placeholder
fallback raised. It did not establish that the separately measured LLM failed.
New rows separate the original Jev reason from `outcome_reason`.

After a fix, use **Run workflow → main** to start with the updated code. **Re-run
jobs** on an old run reuses that run's old commit. Old artifacts cannot recover
HTTP status or usage that the old collector discarded. Keep old results unchanged;
new collectors use `diagnostics_version=1` and reject mixing old run/policy metadata.

When smoke passes, benchmark modes collect development data, select a threshold, freeze the policy, and
collect/evaluate test data. If no eligible fully priced threshold is selected,
test and live calls are skipped. This is a valid experimental outcome, not a
workflow crash. Early stops return a nonzero exit code so Actions does not show
an incomplete evaluation as green. Reports are still uploaded by the `always()`
artifact step. The summary starts with the requested mode, `INCOMPLETE` and the
completed report stages; `status.json` records the same information.

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
   [benchmark walkthrough](README.md), preserving provider, response format, model, timeout, dataset and
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

## Provider references

Presets follow the official API contracts:
[DeepSeek JSON output](https://api-docs.deepseek.com/guides/json_mode/),
[OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai),
[Kimi Chat Completions](https://platform.moonshot.ai/docs/api/chat), and
[Kimi China quick start](https://platform.moonshot.cn/docs/guide/start-using-kimi-api).
Compatibility is covered by mock HTTP tests; live provider behavior still needs
your smoke run. Default reasoning settings, token accounting, caching and billing
can differ between services. Record those limitations when publishing a comparison.
