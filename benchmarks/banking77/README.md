# BANKING77: Jev routing benchmark

Compare **LLM-only**, **Jev-only**, and **Jev + the same LLM fallback** on a public,
labeled intent-classification task. Run locally without a JevCalc account. This
benchmark **never enables telemetry**, including when `JEVCALC_API_KEY` is set.

The implementation and tests have been exercised with synthetic provider
responses. **No live model accuracy, latency or savings result is included.**

## Quick start

Goal: evaluate whether Jev + fallback can reduce classification costs while
maintaining accuracy close to the LLM baseline. Run `demo` to check your
installation, then follow this sequence:

`prepare → collect smoke → collect dev → analyze dev → collect test → analyze test`

- `demo` runs entirely offline with synthetic responses and fictional prices.
  Its results do not represent model performance.
- `collect` calls the live Jev and OpenAI APIs and incurs charges. API keys are
  read only from environment variables.
- The default development split contains 5 examples per class (385 total), and
  the test split contains 10 per class (770 total). Every request includes all
  77 candidate classes.
- Select a threshold on development data, then evaluate the test split using
  the generated `policy.json`. Test reports do not search for a new threshold.
- Verify and enter pricing yourself. Unknown usage or prices remain unknown
  and are not treated as free.
- Offline cascade replay simulates predictions and costs; it does not report
  measured cascade P50/P95. Use `collect --policy` to measure the actual Router
  chain.
- Store local results in the gitignored `benchmark-results/` directory used
  below. Review reports before publishing; do not commit API keys or private data.
- The Router currently uses `jev-latest`, a moving alias. Recording the run date
  does not guarantee identical results in future runs.

The commands below use Bash. In PowerShell, set keys with
`$env:TYPESAFE_API_KEY` and `$env:OPENAI_API_KEY`, and use the Python executable
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
| dev | Training, 5 rows per intent | 385 | Prompt/config checks and threshold selection |
| test | Test, 10 rows per intent | 770 | Evaluate the frozen policy |

Identical wording in the training and test sources is excluded from the test
pool (after stripping whitespace and case-folding); the exclusion count is
recorded. At the pinned revision, 6 overlapping test rows are excluded (3,074
remain for `--test-per-class 0`). This is not paraphrase deduplication. The manifest stores all 77 labels,
readable descriptions derived by replacing underscores with spaces, instructions,
seeds, selected IDs and split hashes. The ground-truth label is never sent to a
provider. Sampling is reproducible within the recorded Python version.

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

Set `TYPESAFE_API_KEY` and `OPENAI_API_KEY` securely in your shell. Choose an OpenAI
model available to your account that supports strict JSON schema on Chat
Completions. There is no default model or hardcoded vendor pricing.

```bash
# Use an actual model ID available to your account, not the placeholder below.
export BENCHMARK_MODEL='YOUR_MODEL_ID'
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split smoke \
  --model "$BENCHMARK_MODEL" --output benchmark-results/smoke-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/smoke-run --output benchmark-results/smoke-report
```

**Paid calls:** paired collection makes one Jev and one LLM request per sample
(40 for smoke, 770 for dev, 1,540 for the default test split), before any separate
live-cascade run. Confirm the smoke results before increasing volume. Requests
are sequential, with connection reuse; `--delay 0.5` optionally spaces samples.
Use `--timeout` to set both provider deadlines. No hidden retry loop is added.

Outputs:

- `run.json`: models, SDK/Python versions, dataset manifest, dates, configuration,
  ordered sample IDs, completion state.
- `results.jsonl`: sample ID, truth, predictions, Jev confidence, outcome states,
  measured elapsed times, separate token usage. No keys or raw provider bodies.

Interrupted runs retain completed rows. Continue with the same command plus
`--resume`. Configuration mismatches are rejected. An interrupted sample may be
called again if it was not fully saved; billed attempts before a crash are not
recoverable from local results. A process lock blocks simultaneous writers.
After a hard kill, remove `.running` only when no collector is active. A malformed
JSONL file is rejected rather than silently dropping records.

## 4. Collect development results and freeze a threshold

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split dev \
  --model "$BENCHMARK_MODEL" --output benchmark-results/dev-run
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

The selector chooses the lowest estimated-cost candidate whose **development**
accuracy is no more than 0.01 below baseline (one percentage point). Ties prefer
higher accuracy, then a higher threshold. The default margin is an experiment
setting, **not a guarantee of production quality or statistical equivalence**.
A selected policy does not necessarily save money; check its cost against the
baseline. If no fully priced eligible candidate exists, the report explains why
and **no policy is written**. Unknown costs cannot win the selection.

`policy.json` freezes the threshold, dataset/config identity, model, timeout,
SDK version, pricing, development IDs and development-result hash. Inspect it
before proceeding. Selection is allowed only for the `dev` split; smoke reports
are exploratory.

## 5. Evaluate the held-out test split

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split test \
  --model "$BENCHMARK_MODEL" --output benchmark-results/test-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/test-run \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/test-report
```

Only the frozen threshold is evaluated, even if `--thresholds` is supplied.
Model, dataset, timeout and pricing changes are rejected against the policy.
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
| `policy.json` | Selected/frozen policy, only when available |

All requests, including provider errors, stay in the accuracy denominator. Jev
confidence is the API's `confidence` field, **not** the largest option probability.
The probe accepts all valid Jev answers using threshold 0; replay then applies
candidate thresholds. Transient/malformed Jev results may fall back; HTTP
401/403/400/422 and redirects follow Router's non-recoverable request-error
policy. LLM failures remain failures. No branch silently substitutes a correct
answer. Jev usage may be unavailable on error paths; it remains unknown.

Replay cost per sample is Jev cost plus LLM cost **only when replay falls back**.
The separate collection-cost field includes both calls on **every** sample.
A partial cost subtotal is not a complete total. Baseline-relative savings are
only calculated when both full costs are known.

## 6. Measure the actual cascade separately

```bash
python -m jev_agent_router.benchmark collect \
  --dataset benchmark-results/data --split test \
  --model "$BENCHMARK_MODEL" \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/live-run
python -m jev_agent_router.benchmark analyze \
  --run benchmark-results/live-run \
  --policy benchmark-results/dev-report/policy.json \
  --output benchmark-results/live-report
```

This executes the existing Router, sequentially calling the LLM only when its
policy calls for fallback. Its P50/P95 are observed wall-clock measurements
including fallback overhead. It costs additional provider calls. The exact
frozen policy must accompany analysis.

Paired replay deliberately reports **no cascade P50/P95**; sums of independent
measurements are not presented as observed chain latency. Live reruns may differ
in predictions, service load and model version. For a defensible timing comparison,
run baseline and cascade in the same environment/time window, record region and
network conditions, and repeat if variance is material. Demo timings are never
model benchmarks.

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
