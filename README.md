# jev-agent-router

An independent, MIT-licensed Python MVP bridging async agent applications to **Jev Choice** decisions. Jev runs first; a confidence gate accepts its selection or delegates to a validated async fallback. The package returns data, **never executes a selected tool, Skill, agent, or shell command**.

This is a local open-source package, not an official Typesafe integration and not an existing jevcalc.com SaaS service. Nothing is published by this project setup. **Score and Noul are out of the MVP.**

## Architecture

```text
application / optional framework tool
             |
      validate state + criteria
             |
 POST https://api.typesafe.ai/v1/systemone
             |
 validate Choice + complete probability distribution
             |
 confidence >= threshold (default 0.8)?
       yes /                         \ no / transient / malformed
 Decision(origin=jev)               async fallback
                                         |
                               validate allowed label
                                         |
                         Decision(origin=fallback, confidence=null)
             |
 application-owned policy / human review / authorized dispatch
```

The gate uses the **API's `confidence` field**, not the highest option probability. Neither confidence nor an LLM fallback guarantees correctness, and fallback does **not** ensure 100% accuracy. Evaluate thresholds on representative labeled data. There are no guaranteed savings claims or hardcoded pricing promises.

Official contract references: [API](https://docs.typesafe.ai/api.md), [confidence](https://docs.typesafe.ai/confidence.md). The implemented request is:

```json
{"state":"invoice","model":"jev-latest","questions":{"route":{"type":"choice","instructions":"Route support","criteria":{"billing":"Payments","technical":"Bugs"}}}}
```

Authorization is `Bearer TYPESAFE_API_KEY`; response parsing reads `answers.route.type`, `choice`, `confidence`, `probabilities`, and optional `usage.input_tokens` / `output_tokens`.

## Install and run offline

Python 3.11+. Only `httpx` and Pydantic are core dependencies; no framework or OpenAI SDK is imported by core.

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python examples/offline.py
.venv/bin/python -m pytest -q
```

The example uses **synthetic fixtures through httpx.MockTransport**, with a high-confidence Jev-path result and a low-confidence fallback-path result. It makes no live requests and uses no real key. The fallback is an explicit review policy, not a simulated LLM response.

## Reproducible BANKING77 benchmark

Compare a structured-output LLM, Jev alone, and confidence-gated Jev + the same
LLM fallback on labeled public data. The local benchmark includes pinned data,
seeded development/test splits, resumable paired collection, development-only
threshold selection, held-out reporting, and separate live cascade measurement.
No JevCalc account is required and benchmark telemetry is always disabled.

Start with an explicitly synthetic, no-network demo:

```bash
python -m jev_agent_router.benchmark demo --output benchmark-results/demo
```

See [the BANKING77 walkthrough](benchmarks/banking77/README.md) for live commands,
pricing assumptions, report interpretation, and quick-start notes.
**The included demo and tests are synthetic; no measured model-performance or
savings claims are shipped.**

Run the same benchmark in your browser with the manual
[GitHub Actions workflow](benchmarks/banking77/ACTIONS.md). It defaults to the
offline demo; live modes use repository Secrets and require explicit paid-call
confirmation. Reports are attached to the workflow run.

## Agent Skill (Codex / Claude Code / OpenClaw / pi / Hermes)

The portable [jev-router Skill](skills/jev-router/SKILL.md) teaches when and how to
use the same MCP/CLI router: bounded choices, minimal context, validated results,
no duplicate fallback, and normal action approval. It is not automatic interception.
Copy the entire directory only after approval; see its
[installation matrix](skills/jev-router/references/integrations.md).
For OpenClaw this supersedes the minimal `integrations/openclaw/jev-route` workflow;
do not activate both. No user-local skill has been installed by this project.

A stdlib helper `skills/jev-router/scripts/route_file.py` sends a private JSON file
to the actual CLI via stdin with a timeout and no shell interpolation.
Tests run that helper against the real CLI with explicitly synthetic offline data.
No live provider or full agent-host skill session has been verified.
The wheel also ships the directory at `jev_agent_router/skills/jev-router`,
accessible using `importlib.resources.files('jev_agent_router') / 'skills' / 'jev-router'`.

## Live application example (not live-tested)

```python
import asyncio
from jev_agent_router import Router
from jev_agent_router.openai import OpenAIJSONFallback

async def main():
    # Reads TYPESAFE_API_KEY and OPENAI_API_KEY from the environment.
    # Choose a model supporting strict JSON schema on Chat Completions.
    fallback = OpenAIJSONFallback(model="gpt-4.1-mini", timeout=20)
    router = Router(fallback=fallback, threshold=0.8,
                    jev_timeout=8, fallback_timeout=25)
    result = await router.route(
        {"message": "Please explain this invoice"},
        {"billing": "Payments and invoices", "technical": "Product bugs"},
        instructions="Route the support request",
    )
    print(result.model_dump_json())
    # Validate authorization/business policy before application-owned dispatch.

asyncio.run(main())
```

Missing/empty keys fail immediately with `ConfigurationError`. OpenAI fallback posts directly to `https://api.openai.com/v1/chat/completions` using strict JSON schema with an enum of allowed labels. It rejects refusal, truncation, unknown labels, malformed JSON and extra fields locally. No confidence is invented. Model availability/schema support must be checked with your account.

### Bring your own async fallback

```python
from jev_agent_router import FallbackChoice, RouteRequest

async def review_policy(request: RouteRequest) -> FallbackChoice:
    # Include human_review in your criteria; no action is executed here.
    return FallbackChoice(label="human_review")
```

The fallback accepts a `RouteRequest` and returns a `FallbackChoice` or a matching dictionary (`{"label": "..."}`, optionally `usage`). Unknown labels, unexpected fields (including `confidence`), exceptions and timeouts become `FallbackError`. Bare strings are not accepted. The fallback receives a deep copy so it cannot mutate the router's allowed-label set. The application decides how to handle a typed failure; no silent default selection occurs.

## Optional framework tools

Install the appropriate extra locally, e.g. `uv pip install --python .venv/bin/python -e '.[langchain]'`. Imports are lazy. Every wrapper accepts fixed `criteria`, optional `instructions` and `name`, and exposes one **text `state`** argument returning Decision JSON. Core additionally accepts JSON object/array state.

| Extra / factory in `jev_agent_router.adapters` | Verified installed version | Verified execution surface | Limits |
|---|---|---|---|
| `langchain` / `langchain_tool` | langchain-core 1.6.3 | `await tool.ainvoke({"state": "invoice"})` | async StructuredTool only; no full agent run |
| `crewai` / `crewai_tool` | crewai 1.15.22 | `await tool.arun(state="invoice")` | `_run` explicitly raises; synchronous Crew execution unsupported |
| `pydantic-ai` / `pydantic_ai_tool` | pydantic-ai-slim 2.46.0 | actual `Agent(TestModel(), tools=[tool]).run(...)` | offline TestModel, not a live provider |
| `autogen` / `autogen_tool` | autogen-core 0.7.5 | `await tool.run_json({"state":"invoice"}, CancellationToken())` | token cancellation tested; no full agent team run |

```python
from jev_agent_router.adapters import langchain_tool

tool = langchain_tool(router, {"billing": "Payments", "technical": "Bugs"})
# Within your async application:
result_json = await tool.ainvoke({"state": "invoice"})
```

These are lightweight native tool adapters, not replacements for framework orchestration. There is deliberately no `asyncio.run` sync bridge: injected async HTTP clients must stay in their owning event loop. No compatibility claim is made for every release within the optional dependency ranges.

## Failure, validation and timeout policy

- One Jev attempt and at most one fallback; **no retry loop**, including on 401/422.
- HTTP 429 and 5xx (including 529), HTTP transport failures and timeouts go to fallback.
- Other non-2xx statuses (including 401, 403, 400, 422 and redirects) raise sanitized `JevRequestError`; fallback is not called. Redirect following is disabled.
- Missing/unknown/malformed Choice answers go to fallback. Confidence and each probability must be numeric, finite, in `[0, 1]`; numeric strings and booleans are rejected.
- The selected label must be allowed; distribution keys must exactly match all criteria and probabilities sum to one within absolute tolerance `1e-6`.
- Criteria contain 1–255 nonempty string labels/descriptions. State is text or JSON object/array. Invalid input fails locally before HTTP.
- Default deadlines are 10 seconds for Jev and 30 seconds for fallback, configurable to positive finite seconds. Both httpx timeout and outer asyncio timeout are applied.
- Cancellation propagates as `asyncio.CancelledError`, including fallback and AutoGen token cancellation. Async deadlines are cooperative: blocking callbacks or fallbacks that suppress cancellation cannot be forcibly preempted. Use trustworthy nonblocking implementations.
- An injected `httpx.AsyncClient` is caller-owned and never closed by the router. Without injection each HTTP call uses a short-lived context-managed client; inject a client for pooling.
- `Decision.usage` is validated Jev usage; `fallback_usage` is separate. Missing token counts are `null`, not fabricated zeros. Invalid responses may lose usage attribution.

## Privacy and observation

No analytics upload, telemetry HTTP client or background worker is created unless you explicitly pass `jevcalc_api_key`. No telemetry is persisted or logged. **Normal live routing sends state, criteria and instructions to Typesafe; fallback may send them to your configured provider.** Review those providers' data policies. Tool frameworks may separately trace prompts/results: configure their telemetry independently.

### Optional JevCalc telemetry (MVP; service not deployed)

The event schema is `jev-telemetry-contract.md` v1, which lives in the
`jevcalc-api` repository and is implemented by three codebases that must change
together: this SDK's `telemetry.py`, the API's `metrics.ts` and the console's
mirrored types. `fallback_model` in particular is a closed enum — a model
outside it is reported as `other`, which the API prices as unknown and excludes
from savings, so the list going stale silently disables that figure rather than
failing loudly. `test_fallback_model_enum_matches_shared_contract` pins it.

```python
async with Router(
    jev_api_key=provider_key,  # alias of api_key; conflicting values rejected
    jevcalc_api_key=dashboard_key,  # explicit opt-in; omit for zero telemetry
    fallback=my_fallback,  # optional: omission raises AbstentionError if Jev cannot decide
) as router:
    decision = await router.route(state, criteria)
```

The SDK **does not read `JEVCALC_API_KEY` from the environment**. CLI and MCP
explicitly propagate that optional environment variable via their shared bridge;
both close the router on exit (including errors). Their offline fixture flag never
enables telemetry, even if the variable is set. Existing provider credentials and
fallback configuration remain separate.

The default endpoint is `https://jevcalc.com/api/v1/events`. It is the agreed API
contract, **not a currently deployed or verified upload service**. An explicit
`telemetry_endpoint="http://localhost:3210/api/v1/events"` is supported for local
development. Remote HTTP, URL credentials/query/fragment and redirects are rejected.
Use only a trusted endpoint: its server receives the JevCalc authorization key.

Only schema-v1 operational metadata is sent: UUID/time, measured Jev input tokens
(unknown remains null), **one question per route** regardless of candidate count,
total/Jev/fallback durations, observed Jev HTTP status (null for timeout), validated
Jev confidence (retained in telemetry on fallback), origin/reason enums, and
fallback model/usage. Model names are limited to `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`,
`gpt-4.1-mini`, or `other`; custom names never leave through telemetry. OpenAI
fallback populates these fields; custom callbacks may return `FallbackChoice.model`
using the same enum. `Decision.confidence` remains null for fallback decisions,
because Jev's confidence is not confidence in the fallback's selected label.

No state, instructions, criteria, label, probability map, response/exception text,
provider API key, arbitrary tag, machine or user identifier is uploaded. The JevCalc
key is sent only in the authorization header. Network infrastructure still sees IP
addresses; this is not network anonymity.

The lazy worker starts only inside a running loop, uses a memory queue (default 256;
`telemetry_queue_size` configurable), batches at most 100 events / 128 KiB, drops
overflow, and tries at most three sends with bounded jitter for network/429/5xx
failures. Authentication errors and redirects are not retried. Routing never waits
for reporting. `await router.flush(timeout=1.0)` returns whether the queue drained,
**not whether uploads succeeded**; failed batches count as drained.
`await router.aclose(timeout=1.0)` / async context exit stop accepting events,
attempt a bounded flush and cancel the worker, dropping remaining queued events.
The timeout includes cleanup; cancellation-resistant custom test transports may
finish cleanup later but cannot extend the caller's deadline. Like all asyncio
timeouts, this assumes the event loop itself is not blocked. Reuse within one loop,
do not route after close, and close explicitly before shutting down that loop.
Local worker counters (`sent`, `failed`, `dropped`) are available on
`router._telemetry` for diagnostics; they contain no content.

Injected synthetic provider transports suppress reporting unless the private
test-only `_telemetry_transport=httpx.MockTransport(...)` is also supplied; that
hook rejects real network transports. Tests use only isolated synthetic captures,
not real dashboard or provider credentials.

An optional synchronous `Observer` protocol receives only `DecisionEvent` metadata via `on_decision(event)`: `origin`, reason code, Jev/fallback elapsed milliseconds, and reported input/output token counts. No state, prompt, label, criteria, key, raw response or exception text is provided. Token counts aggregate known values and may be partial, not billing totals. Observer exceptions are ignored. Keep callbacks fast/nonblocking; implement any queue/export in your application. Error messages deliberately omit provider response bodies. Do not enable HTTP debug logging on sensitive workloads.

For the framework test run, telemetry was explicitly disabled with:

```bash
CREWAI_TELEMETRY_DISABLED=true OTEL_SDK_DISABLED=true LANGCHAIN_TRACING_V2=false \
  .venv/bin/python -m pytest -q
```

## Verification and packaging

Tests exercise real routing/validation with **mock HTTP**, plus actual installed framework tools (not fake framework classes). Optional framework tests skip when their dependencies are absent. No live Jev/OpenAI request was made: user credentials were unavailable, so service availability, real accuracy, latency, cost and provider interoperability remain unverified.

```bash
uv pip install --python .venv/bin/python -e '.[all,dev]'
.venv/bin/python -m pytest -q
uv build --python .venv/bin/python
# dist/jev_agent_router-0.1.0-py3-none-any.whl
# dist/jev_agent_router-0.1.0.tar.gz
```

See [VERIFICATION.md](VERIFICATION.md) for executed evidence. MVP limitations also include no Score/Noul support, no calibration/training, no batching, no streaming, no persistent retry queue, no tool execution and no jevcalc.com deployment. Build on the observer boundary for future services, without claiming those services already exist.
