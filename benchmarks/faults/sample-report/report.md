# Offline routing fault experiment

**Synthetic fixtures, not provider reliability or production latency. No API keys or network calls.**

Baseline: the same validated Router, threshold 0, no fallback. Cascade: threshold 0.8 with the real
ChatJSONFallback parser. Only the policy changes; this does not compare the SDK to every custom implementation.

Contract checks: 693/693. Repeats: 3.
HTTP request counts are mocked provider attempts, not billable calls. No retries.

| Scenario | Strategy | Outcome | Label | Jev / LLM calls | Diagnostic | Contract |
|---|---|---|---|---|---|---|
| healthy | jev-only | decision | billing | 1 / 0 | confident | PASS |
| healthy | cascade | decision | billing | 1 / 0 | confident | PASS |
| low_confidence_corrected | jev-only | decision | technical | 1 / 0 | confident | PASS |
| low_confidence_corrected | cascade | decision | billing | 1 / 1 | low_confidence | PASS |
| confidently_wrong | jev-only | decision | technical | 1 / 0 | confident | PASS |
| confidently_wrong | cascade | decision | technical | 1 / 0 | confident | PASS |
| fallback_can_regress | jev-only | decision | billing | 1 / 0 | confident | PASS |
| fallback_can_regress | cascade | decision | technical | 1 / 1 | low_confidence | PASS |
| rate_limit | jev-only | abstained | — | 1 / 0 | http_error | PASS |
| rate_limit | cascade | decision | billing | 1 / 1 | http_error | PASS |
| server_error | jev-only | abstained | — | 1 / 0 | http_error | PASS |
| server_error | cascade | decision | billing | 1 / 1 | http_error | PASS |
| jev_timeout | jev-only | abstained | — | 1 / 0 | timeout | PASS |
| jev_timeout | cascade | decision | billing | 1 / 1 | timeout | PASS |
| network_error | jev-only | abstained | — | 1 / 0 | network_error | PASS |
| network_error | cascade | decision | billing | 1 / 1 | network_error | PASS |
| invalid_json | jev-only | abstained | — | 1 / 0 | invalid_json | PASS |
| invalid_json | cascade | decision | billing | 1 / 1 | invalid_json | PASS |
| unknown_label | jev-only | abstained | — | 1 / 0 | invalid_labels | PASS |
| unknown_label | cascade | decision | billing | 1 / 1 | invalid_labels | PASS |
| invalid_probability_sum | jev-only | abstained | — | 1 / 0 | invalid_probability_sum | PASS |
| invalid_probability_sum | cascade | decision | billing | 1 / 1 | invalid_probability_sum | PASS |
| authentication_error | jev-only | request_error | — | 1 / 0 | http_error | PASS |
| authentication_error | cascade | request_error | — | 1 / 0 | http_error | PASS |
| fallback_timeout | jev-only | decision | billing | 1 / 0 | confident | PASS |
| fallback_timeout | cascade | fallback_error | — | 1 / 1 | fallback_failed | PASS |
| fallback_server_error | jev-only | decision | billing | 1 / 0 | confident | PASS |
| fallback_server_error | cascade | fallback_error | — | 1 / 1 | fallback_failed | PASS |
| fallback_invalid_label | jev-only | decision | billing | 1 / 0 | confident | PASS |
| fallback_invalid_label | cascade | fallback_error | — | 1 / 1 | fallback_failed | PASS |
| cancel_during_jev | jev-only | cancelled | — | 1 / 0 | cancelled | PASS |
| cancel_during_jev | cascade | cancelled | — | 1 / 0 | cancelled | PASS |
| cancel_during_fallback | cascade | cancelled | — | 1 / 1 | cancelled | PASS |

## Observed local timings

Includes successes, intentional failures and cancellations. Timeouts are injected at 50 ms;
timings depend on the local scheduler, and are not SDK overhead estimates or provider comparisons.

| Strategy | Executions | Decisions returned | Correct fixture decisions | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|
| jev-only | 48 | 21 | 15 | 0.597 | 33.785 |
| cascade | 51 | 33 | 27 | 1.177 | 51.800 |

## What this establishes

- Recoverable transport/response faults can reach a validated fallback, with bounded attempt counts.
- HTTP 401 stops without fallback. Cancellation propagates. Invalid fallback output returns an error.
- A confidently wrong Jev answer remains wrong. A fallback can replace a correct answer with a wrong one.
- Contract PASS includes expected errors; it does not mean every request returned a correct decision.
- The fallback-stage cancellation case has no Jev-only execution because that baseline never calls a fallback.
- The scenario mix is hand-picked, not a measured incident distribution; do not advertise aggregate reliability gains.
- Returned labels are data. This experiment does not authorize or execute tools.

Reproduce: `python -m jev_agent_router.benchmark faults --output benchmark-results/faults --repeats 3`.
`report.json` includes all repeated rows, expected outcomes, sanitized observer events and checks.
