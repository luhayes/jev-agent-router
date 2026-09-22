# Offline fault experiment

Run the real Router and ChatJSONFallback against isolated HTTP fixtures. No API
keys, telemetry, model tokens, or network calls are needed by the experiment.
Installing dependencies still requires access to the package index.

```bash
python -m pip install -e '.[dev]'
python -m jev_agent_router.benchmark faults --output benchmark-results/faults --repeats 3
```

Use a fresh output directory on rerun. Exit code 0 means all behavior contracts
passed; 1 means at least one mismatch. `report.md` is readable, `report.json`
contains every repeated observation, expected result, call count, timing and
sanitized observer diagnostic. Timings vary between machines.

The control is **the same validated Router at threshold 0, with no fallback**.
The treatment uses threshold 0.8 and the actual JSON fallback parser. Both share
response validation. This isolates the effect of the policy; it is not a claim
that developers cannot implement the same behavior themselves.

Seventeen cases cover: ordinary success, low-confidence correction, confident
error, fallback regression, 429, 503, Jev timeout, network failure, malformed JSON,
unknown label, invalid probability sum, 401, fallback timeout, fallback 503,
fallback invalid label, and cancellation during each provider stage. The fallback
cancellation case applies only to cascade. Three repetitions produce 99 executions.

Each execution checks its outcome, one Jev attempt, at most one fallback, one
observer event, allowed label or no decision, the Jev diagnostic and cancellation
propagation. Expected errors count as contract PASS, not a successful answer.
Cancellation is externally requested after the fixture enters the relevant stage.

[Checked-in example report](sample-report/report.md) is an actual local execution
of these synthetic cases. The JSON is retained alongside it. It is not measured
provider uptime or model quality. A hand-picked failure mix must not be converted
into a production availability improvement. Local P50/P95 includes intentional
50 ms timeouts, errors and cancellation; it is not a performance claim.

The [manual Actions workflow](../../.github/workflows/decision-validation.yml)
runs the offline decision demo, tests and this experiment, then attaches reports.
It has no provider Secrets and cannot start a paid benchmark. CI runs the same
checks when relevant code changes.
