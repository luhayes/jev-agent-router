# Local verification evidence

All operations were scoped to `/Users/lujuhong/clawd/jev-agent-router`. No Codex CLI, global installs, commits, pushes, publication, deployment, or changes to jevcalc were performed.

## Test-first execution record

These are observed tool results, not generated example outputs:

1. Before package source existed: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_router.py -q` → **2 failed**, including the explicit package-existence assertion and missing Router import.
2. Implemented first confident HTTP Choice path: full suite → **2 passed**.
3. Added safety/fallback tests before implementing those behaviors: `tests/test_safety.py` → **35 failed** (missing validation/error/fallback/configuration behavior).
4. Implemented core validation, confidence gating, bounded fallback, cancellation and observer: full suite → **37 passed**.
5. Added OpenAI structured-fallback tests before module: `tests/test_openai.py` → **6 failed**. Implemented fallback: full suite → **43 passed**.
6. Added adapter tests before module: `tests/test_adapters.py` → **6 failed**. Installed actual frameworks locally and implemented native wrappers: full suite → **49 passed**.
7. After formatting: Ruff → **All checks passed**; full installed-framework suite → **49 passed in 2.15s**.

The first missing-module failures establish absence, not behavioral correctness; subsequent green runs exercise real implementation against HTTP fixtures. The safety slice contains parameterized adversarial cases, not claims of exhaustive testing.

## Installed versions

Python **3.11.16**; package **0.1.0**; httpx **0.28.1**.

| Package | Framework-test venv |
|---|---|
| pydantic | 2.12.5 |
| langchain-core | 1.6.3 |
| crewai | 1.15.22 |
| pydantic-ai-slim | 2.46.0 |
| autogen-core | 0.7.5 |

Framework smoke tests executed LangChain `ainvoke`, CrewAI `arun` (and explicit sync rejection), Pydantic AI `Agent(TestModel)` plus its actual Tool function, and AutoGen `run_json` including CancellationToken propagation. These use real installed libraries, not fake framework classes. No full LangChain/CrewAI/AutoGen agent application or live model was tested.

## Distribution verification

`uv build --python .venv/bin/python` successfully built:

- `dist/jev_agent_router-0.1.0.tar.gz`
- `dist/jev_agent_router-0.1.0-py3-none-any.whl`

The wheel was installed into a separate `.verify-venv` with core dependencies and test tools only. `pytest -q` returned **44 passed, 5 skipped in 0.44s**; the five skips are optional-framework execution/cancellation tests. This second environment resolved Pydantic **2.13.5**. The lazy-import test passed without any optional framework installed.

`examples/offline.py` ran in both environments, producing:

- billing: origin `jev`, confidence `0.9`, reason `confident`;
- human_review: origin `fallback`, confidence `null`, reason `low_confidence`.

These are explicitly synthetic MockTransport fixtures, not observed Jev service responses. The offline demonstration did not contact any API.

## Remaining limits

No user API credentials were provided. Live Jev/OpenAI connectivity, deployed model schema support, decision accuracy, pricing, latency and savings remain **unverified**. No SaaS control plane exists. Score/Noul and automatic action execution are intentionally absent. Optional package version ranges are not an exhaustive compatibility certification.

An initial Ruff run found compact test formatting violations; formatting corrected these and the subsequent lint and complete suite passed. CrewAI installation brought substantial optional dependencies and constrained Pydantic to 2.12.5; this is isolated to `.venv`, not the global Python environment.
