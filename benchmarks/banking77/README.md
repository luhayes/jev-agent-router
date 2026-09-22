# BANKING77: Jev routing benchmark

Compare **LLM-only**, **Jev-only**, and **Jev + the same LLM fallback** on a public,
labeled intent-classification task. Run locally without a JevCalc account. This
benchmark **never enables telemetry**, including when `JEVCALC_API_KEY` is set.

The implementation and tests have been exercised with synthetic provider
responses. **No live model accuracy, latency or savings result is included.**

Prefer running in the cloud? See the [GitHub Actions guide](ACTIONS.md) for a
manual workflow with an offline default, Secrets-based live calls, and downloadable
reports.

## Quick start

Goal: evaluate whether Jev + fallback can reduce classification costs while
maintaining accuracy close to the LLM baseline. Run `demo` to check your
installation, then follow this sequence:

`prepare → collect smoke → collect dev → analyze dev → collect test → analyze test`

- `demo` runs entirely offline with synthetic responses and fictional prices.
  Its results do not represent model performance.
- `collect` calls live Jev and the selected LLM service and incurs charges. API keys are
  read only from environment variables.
- The default development split contains 5 examples per class (385 total), and
  the test split contains 10 per class (770 total). Every request includes all
  77 candidate classes.
- Select Jev-only, LLM-only, or a cascade threshold on development data, then
  evaluate the test split using `policy.json`. Test reports never reselect the strategy.
- Verify and enter pricing yourself. Unknown usage or prices remain unknown
  and are not treated as free.
- Offline cascade replay simulates predictions and costs; it does not report
  measured cascade P50/P95. Use `collect --policy` to execute the selected strategy live.
- Store local results in the gitignored `benchmark-results/` directory used
  below. Review reports before publishing; do not commit API keys or private data.
- The Router currently uses `jev-latest`, a moving alias. Recording the run date
  does not guarantee identical results in future runs.

The commands below use Bash. In PowerShell, set keys with
`$env:TYPESAFE_API_KEY` and the selected provider key (for example, `$env:DEEPSEEK_API_KEY`), and use the Python executable
from your virtual environment.

## 1. Install and run the no-network demo

From the repository root, using Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m jev_agent_router.benchmark demo --output benchmark-results/demo
```

`jev-benchmark` is also installed as a console command. The module form above
works identically. No additional data-science packages are required.

Inspect `benchmark-results/demo/test-report/report.md` and
`benchmark-results/demo/live-report/report.md`. Every demo report is marked
**SYNTHETIC**. The mock transport exercises the actual Router and OpenAI fallback
parsing, including low-confidence fallback. Even provider API keys already in
your environment will not cause network requests in the demo.

## 2. Prepare reproducible data

```bash
python -m jev_agent_router.benchmark prepare \
  --output benchmark-results/data --seed 42
```

The downloader pins PolyAI's dataset to commit
`57ec275d8078af65b7731c2a98be812d844a6d6b` and records both source-file SHA-256
hashes. It creates:

| Split | Default source | Size | Purpose |
|---|---|---:|---|
| smoke | Training rows not used in dev | 20 | Check credentials and output contract |
| dev | Training, 5 rows per intent | 385 | Prompt/config checks and strategy selection |
| test | Test, 10 rows per intent | 770 | Evaluate the frozen policy |

Identical wording in the training and test sources is excluded from the test
pool (after stripping whitespace and case-folding); the exclusion count is
recorded. At the pinned revision, 6 overlapping test rows are excluded (3,074
remain for `--test-per-class 0`). This is not paraphrase deduplication. The manifest stores all 77 labels,
versioned English descriptions reviewed against training examples, instructions,
seeds, selected IDs and split hashes. The ground-truth label is never sent to a
provider. Sampling is reproducible within the recorded Python version.

See [category definitions and review notes](CRITERIA.md). In particular, the
historical `get_physical_card` label refers to obtaining/viewing a card PIN in
the pinned training data; physical-card ordering is `order_physical_card`.
Descriptions preserve original labels and are shared by both providers.
The manifest records their version and text as part of the dataset hash, so
old policies cannot be used with revised descriptions. Start a new preparation
and run; longer descriptions may increase token costs. Local `--data-dir` CSVs
must use the exact BANKING77 category vocabulary.

For an existing local download, use `--data-dir /path/to/banking_data` containing
`train.csv` and `test.csv`. Local data is identified by content hashes rather than
claimed to match the upstream commit. Keep the original source files if you need
an exact rerun. If your environment uses a SOCKS proxy, install `httpx[socks]`.

For a full-test experiment, prepare a **new dataset directory before collecting**:

```bash
python -m jev_agent_router.benchmark prepare \
  --output benchmark-results/full-data --test-per-class 0
```

The default is an exploratory subset. Keep all candidate labels; do not shortlist
using the expected answer. If you alter descriptions or instructions, start a new
experiment and select a new policy.

## 3. Check 20 live requests first

Set `TYPESAFE_API_KEY` and your selected service's key securely in your shell.
Choose `--provider openai|deepseek|openrouter|gemini|kimi|kimi-cn` and a model
available to your account. OpenAI is the backward-compatible default; other
providers do not need an OpenAI key. See the [provider/key table](ACTIONS.md#add-keys-for-live-evaluation).
There is no default model or hardcoded vendor pricing.

`--response-format auto` uses JSON mode for DeepSeek/Kimi and strict JSON schema
for OpenAI/OpenRouter/Gemini. Override with `json_object` or `json_schema` only
when supported by your model. Both modes validate the exact label locally;
invalid output remains a failure. Keep provider and format identical through
smoke, development, test and live runs. Each invocation calls one selected LLM.

For example, set `BENCHMARK_PROVIDER=deepseek` and supply `DEEPSEEK_API_KEY` for
DeepSeek. Set `BENCHMARK_PROVIDER=kimi-cn` for a China-issued Moonshot key.
The commands below pass the provider explicitly; this environment variable is
only a shell convenience, not a credential or an implicit CLI setting.

```bash
# Use an actual model ID available to your account, not the placeholder below.
export BENCHMARK_PROVIDER='deepseek'
export BENCHMARK_MODEL='YOUR_MODEL_ID'
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split smoke \
  --provider "$BENCHMARK_PROVIDER" --model "$BENCHMARK_MODEL" --output benchmark-results/smoke-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/smoke-run --output benchmark-results/smoke-report
```

**Paid calls:** paired collection makes one Jev and one LLM request per sample
(40 for smoke, 770 for dev, 1,540 for the default test split), before any separate
live-strategy run. Confirm the smoke results before increasing volume. Requests
are sequential, with connection reuse; `--delay 0.5` optionally spaces samples.
Use `--timeout` to set both provider deadlines. No hidden retry loop is added.

Outputs:

- `run.json`: provider, API base URL, resolved output format, adapter version,
  models, SDK/Python versions, dataset manifest, dates, configuration, ordered
  sample IDs and completion state.
- `results.jsonl`: sample ID, truth, predictions, Jev confidence, outcome states,
  measured elapsed times, separate token usage, and sanitized Jev failure
  diagnostics (original reason, HTTP status, error code and probability sum).
  No keys or raw provider bodies.

Interrupted runs retain completed rows. Continue with the same command plus
`--resume`. Configuration mismatches are rejected. To resume a run from before provider
metadata was added, use its original repository commit; do not edit its run
metadata. An interrupted sample may be called again if it was not fully saved; billed attempts before a crash are not
recoverable from local results. A process lock blocks simultaneous writers.
After a hard kill, remove `.running` only when no collector is active. A malformed
JSONL file is rejected rather than silently dropping records.

## 4. Collect development results and freeze a strategy

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split dev \
  --provider "$BENCHMARK_PROVIDER" --model "$BENCHMARK_MODEL" --output benchmark-results/dev-run
cp benchmarks/banking77/prices.example.json benchmark-results/prices.json
```

Edit `benchmark-results/prices.json`: exact model ID, USD **per million tokens**,
pricing date and source URLs. Use `0` only for a verified zero tariff; use `null`
for unknown. The example intentionally contains no claimed prices. Pricing is
an estimate based on input/output usage; cached-token discounts, negotiated
rates and other billing adjustments are not modeled.

```bash
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/dev-run --prices benchmark-results/prices.json \
  --thresholds 0.50 0.60 0.70 0.80 0.90 0.95 --max-drop 0.01 \
  --output benchmark-results/dev-report
```

The selector compares **Jev-only, LLM-only, and all candidate cascade thresholds**.
It chooses the lowest estimated-cost candidate whose **development** accuracy is
no more than 0.01 below the LLM baseline (one percentage point). Ties prefer higher
accuracy, then single-provider strategies (Jev before LLM), then a higher cascade
threshold. The default margin is an experiment setting, **not a guarantee of
production quality or statistical equivalence**. A single-provider winner means
the development results do not justify paying for a cascade under this rule.

Only candidates with complete cost coverage can win. An incompletely priced LLM
baseline still supplies its failure-inclusive accuracy constraint; relative
savings remain unknown. If the LLM baseline is fully priced, it is itself an
eligible option, so the selected dev cost cannot exceed its cost. This is not a
test/production savings guarantee. If no fully priced eligible candidate exists,
the report explains why and **no policy is written**.

`policy.json` schema v2 freezes `strategy` (`jev-only`, `llm-only`, or `cascade`),
`threshold` (null for a single-provider strategy), dataset/config identity, model, timeout,
SDK version, pricing, development IDs and development-result hash. Inspect it
before proceeding. Selection is allowed only for the `dev` split; smoke reports
are exploratory. Legacy schema-v1 policies retain their original cascade meaning.

For diagnosis, the cheapest eligible cascade on dev is also recorded as
`diagnostic_cascade_threshold`, even if a single-provider strategy wins. It is a
comparator, not a second deployment policy. If no cascade meets the dev constraint,
this field is null and test reporting does not invent one.

## 5. Evaluate the held-out test split

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split test \
  --provider "$BENCHMARK_PROVIDER" --model "$BENCHMARK_MODEL" --output benchmark-results/test-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/test-run \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/test-report
```

The frozen strategy is evaluated alongside the two single-provider baselines and,
when present, the single diagnostic cascade threshold frozen on dev. Supplying
`--thresholds` cannot re-sweep the test set or change the policy.
Provider, output format, model, dataset, timeout and pricing changes are rejected against the policy.
Do not tune on the test results and then present the same test set as held out.
Repeated public-benchmark tuning also weakens the interpretation of held-out
results; these public examples may already appear in model training data.

Each report directory contains:

| File | Content |
|---|---|
| `report.md` | Readable comparison and interpretation |
| `report.json` | Full provenance, metrics, per-class counts and Wilson accuracy intervals |
| `metrics.csv` | Flat metrics for plotting or spreadsheets |
| `errors.json` | All errors with IDs, truth, predictions and confidence where available |
| `random-controls.json` | Offline controls matching each reported cascade's fallback call count |
| `policy.json` | Selected/frozen policy, only when available |

All requests, including provider errors, stay in the accuracy denominator. Jev
confidence is the API's `confidence` field, **not** the largest option probability.
The probe accepts all valid Jev answers using threshold 0; replay then applies
candidate thresholds. Transient/malformed Jev results may fall back; HTTP
401/403/400/422 and redirects follow Router's non-recoverable request-error
policy. LLM failures remain failures. No branch silently substitutes a correct
answer. Valid Jev usage is retained before answer validation so a malformed
answer does not discard known billing data. Jev usage may be unavailable on error paths; it remains unknown.

Replay cost per sample is Jev cost plus LLM cost **only when replay falls back**.
The separate collection-cost field includes both calls on **every** sample.
A partial cost subtotal is not a complete total. Baseline-relative savings are
only calculated when both full costs are known.

## 6. Measure the selected strategy separately

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split test \
  --provider "$BENCHMARK_PROVIDER" --model "$BENCHMARK_MODEL" \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/live-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/live-run \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/live-report
```

This executes the frozen strategy: Jev-only makes only Jev requests (errors stay
errors), LLM-only makes only LLM requests, and cascade uses the Router with actual
fallback calls. Single-provider CLI collection requires only that provider's key;
paired collection and the complete Actions pipeline still require both keys.
P50/P95 are observed wall-clock measurements for the selected strategy. This
costs additional provider calls, and the exact policy must accompany analysis.
New policy collections use `mode=policy-live`; legacy cascade policies still use
`mode=cascade-live`. A Jev-only live result is never labeled as a measured cascade.

Paired replay deliberately reports **no cascade P50/P95**; sums of independent
measurements are not presented as observed chain latency. Live reruns may differ
in predictions, service load and model version. For a defensible timing comparison,
run baseline and cascade in the same environment/time window, record region and
network conditions, and repeat if variance is material. Demo timings are never
model benchmarks.

## Random fallback controls and offline reanalysis

Paired reports compare cascade corrections and regressions against Jev-only, and
include a deterministic random fallback control (10,000 simulations, seed 42).
Each simulation matches the cascade's **number of fallback calls**, not its token
cost. Recoverable Jev errors are forced to fall back in every trial;
nonrecoverable request errors never fall back. Randomization chooses the same
number of remaining fallbacks among valid Jev responses, without replacement.
Failed LLM outputs remain failures. No API calls are made.

Reports show actual corrections/regressions, net correct-answer gain, random
expected gain, the central 95% simulation range, and the fraction of simulations
at least as good as the observed cascade. These describe allocations on fixed
outputs, not fresh independent experiments, a confidence interval for deployment
performance, or a generalization guarantee. Dev comparisons are exploratory;
test uses only the dev-frozen diagnostic threshold. Random results never enter
strategy selection. Single-provider or cascade live runs have no paired outputs
and therefore no random control.

To reanalyze an existing extracted artifact without additional paid calls:

```bash
python -m jev_agent_router.benchmark analyze \
  --run extracted/dev-run --prices extracted/prices.json \
  --output benchmark-results/reanalysis/dev-report
python -m jev_agent_router.benchmark analyze \
  --run extracted/test-run \
  --policy benchmark-results/reanalysis/dev-report/policy.json \
  --output benchmark-results/reanalysis/test-report
```

Keep the original files. This creates a new policy from existing dev records and
evaluates it on existing paired test records. It does not create a new live
measurement: old `live-run` results must still be analyzed with the exact original
policy used to collect them. If test results have already been inspected, label
the new analysis retrospective rather than untouched held-out validation.

## Publishing the first case study

Publish the script/version, dataset revision and split IDs, full criteria and
instructions, exact model IDs, run dates, tariff assumptions, summary, and
representative errors. Include confident Jev errors and fallback failures when
present. Review generated artifacts before deliberately publishing them; normal
runs stay in gitignored `benchmark-results/` and are never automatically uploaded.
Do not publish credentials or private workload samples.

Explain that this is English banking-intent classification, not complete agent
execution, tool argument generation, safety authorization, or evidence of all
workload performance. Small accuracy differences and a small per-class sample
size cannot establish equivalence. A poor result is still useful evidence of
where routing should not be applied.

## Attribution

Data: [PolyAI task-specific datasets](https://github.com/PolyAI-LDN/task-specific-datasets),
licensed **CC-BY-4.0**. Cite Iñigo Casanueva, Tadas Temčinas, Daniela Gerz,
Matthew Henderson, and Ivan Vulić, **Efficient Intent Detection with Dual Sentence
Encoders** (2020), [paper](https://arxiv.org/abs/2003.04807).
Sampling, normalized overlap removal and label-description formatting are this
benchmark's transformations, not changes claimed by the dataset authors.
The benchmark code follows this repository's MIT license; dataset attribution
and licensing remain separate.


## Diagnosing a stopped Actions run

`standard` begins with the same smoke check as every live mode. A smoke provider
failure stops later stages, returns a nonzero exit status, and preserves reports.
The summary distinguishes the requested mode from completed report stages.
Check the log's failure counts and `jev_error`/`http_status` in `results.jsonl`.
Jev errors are categorized as HTTP, timeout, network, JSON, usage, answer schema,
label distribution, or probability-sum errors. The original reason is retained
even if the paired probe or actual fallback fails. These fields are local observer
metadata and are not added to the JevCalc telemetry contract.

Cost cells say `unknown (usage or price missing)` when a full estimate cannot be
made. `N/A (no Jev-accepted requests)` means the accepted-error denominator is
zero; `not measured (replay)` denotes unmeasured cascade latency. These are
different from a measured zero. JSON/CSV retain null values for missing metrics.

Diagnostics and usage preservation changed in collector diagnostics version 1.
For old interrupted runs use their original commit; do not combine old policies
with new collections or manually fill missing usage with zero.


### Probability-sum compatibility

A live smoke run returned HTTP 200 with a validated distribution totaling
`0.9900000000000001`. The old `1e-6` sum tolerance classified it as an error.
The router now accepts totals in `[0.99, 1.01]`, with `1e-12` only for arithmetic
at the boundaries. This is a bounded compatibility policy based on the observed
response, not proof of rounding or a tolerance guaranteed by TypeSafe. The
[official Choice documentation](https://docs.typesafe.ai/primitives/choice)
describes a sum of one without specifying rounding precision.

Every probability must still be finite and within `[0, 1]`, distribution keys
must exactly match criteria, and the chosen label must be allowed. Greater total
deviations still fall back. Values are not renormalized, and routing thresholds
still use the separate API confidence. Diagnostics retain the original total.
The tolerance is recorded in run configuration and Markdown reports; resume and
frozen-policy checks reject a changed tolerance. Start a fresh development run
instead of combining old rejection counts with the revised validation policy.
