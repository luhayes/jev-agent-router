# Local agent integrations

These are **opt-in decision tools**, not automatic interception of every agent
call and not a generative-model replacement. All bridges call the same public
`jev_agent_router.Router`; labels are returned as data, never executed.

## Install from this checkout (not PyPI)

Python 3.11+; MCP requires the optional official Python MCP SDK.
From the repository root:

```sh
uv venv .agent-venv
uv pip install --python .agent-venv/bin/python -e '.[mcp]'
. .agent-venv/bin/activate
command -v jev-route
command -v jev-route-mcp
```

The activated environment puts both commands on PATH. For agents launched from
another environment, use the **absolute command path printed above** in their
local configuration. Scripts also work via the installed environment's Python:
`python integrations/cli.py` and `python integrations/mcp_server.py`.
This repository has not been published or installed into any user's agent config.

Live execution requires `TYPESAFE_API_KEY`, `OPENAI_API_KEY`, and
`JEV_FALLBACK_MODEL` (an OpenAI model supporting strict JSON-schema output).
Supply keys through a private environment/secret manager; never command-line
arguments or repository files. Model selection is explicit. The bridge makes one
Jev attempt and, if necessary, one OpenAI fallback using the core defaults.
There is no guessed custom SaaS URL and no reuse of agent OAuth subscriptions.

## Protocol

Send one JSON object on stdin, then close stdin. For example, save this as a
request file using your editor (not shell-interpolated untrusted text):

```json
{"state":"An example ticket","criteria":{"billing":"Payment issue","technical":"Product issue"},"instructions":"Select the best route"}
```

`jev-route < request.json` returns one JSON object:
`{"test_only":false,"decision":{...}}`. See the core `Decision` schema for fields.
Errors return sanitized `{"error":"..."}` and nonzero status. Input is limited
to 1 MiB. `--timeout 45` bounds routing after input is read; callers must close
stdin and impose their own process timeout (50 seconds recommended). No keys,
request values, raw provider errors or dependency logs are printed. Do not put
secrets in state: live state is intentionally sent to the inference providers.

MCP stdio exposes `jev_route` with the same `state`, `criteria`, `instructions`
schema. Stdout contains only MCP JSON-RPC. SDK cancellation propagates to the
async router; each call has the routing timeout. The pi runner uses argv spawning
(no shell), JSON stdin, abort handling, timeout, SIGTERM then SIGKILL escalation,
and a 1 MiB output bound. Stderr is drained without exposing content.

## Agent setup and compatibility

| Agent | Supplied integration | Verified here / limitations |
|---|---|---|
| Codex | `configs/codex.toml`, MCP stdio | MCP protocol verified with real SDK client; config is a documented template, not tested inside Codex |
| Claude Code | `configs/claude.mcp.json`, MCP stdio | Same bridge verified; agent config/startup not run |
| Hermes | `configs/hermes.yaml`, native MCP | Same bridge verified; Hermes discovery not run |
| OpenClaw | `openclaw/jev-route/SKILL.md` | Repository-local skill instructions; skill loading and agent invocation not run |
| pi coding agent | `pi/jev-route.ts` plus `pi/process.mjs` | Native TypeScript registration/execute tested in a host harness through the real CLI; subprocess helper tested; full pi session not run |

**Codex:** merge the TOML snippet into your chosen Codex config after review.
`env_vars` explicitly forwards the three configured variables.

**Claude Code:** merge the JSON into the project's `.mcp.json` after review,
then approve the MCP server. Launch with the credentials/model in its environment.

**Hermes:** use Hermes configuration tooling to add the `mcp_servers.jev` mapping.
Hermes filters stdio subprocess environments, so shell exports alone are NOT
sufficient. Explicitly supply the two keys through its private per-server env /
secret-management setup, or use an owner-only local launcher that retrieves them
from your secret manager and execs the absolute `jev-route-mcp` command. The
checked-in YAML intentionally contains no credentials and is not turnkey until
that private forwarding is configured. Never commit populated secret fields.
Restart Hermes after configuration; expect a tool such as `mcp_jev_jev_route`.

**OpenClaw:** with explicit user approval, copy the `openclaw/jev-route` directory
into the selected workspace's `skills/` directory. The skill requires the local
`jev-route` executable and the three environment variables. It instructs the
agent to use a stdin-capable process API and preserve action approval gates.

**pi:** activate the Python environment, make credentials available privately,
and run from this checkout:

```sh
pi -e ./integrations/pi/jev-route.ts
```

For project-local auto-discovery, copy BOTH the extension and `process.mjs` into
`.pi/extensions/` after review. `JEV_ROUTE_BIN` may specify an absolute executable
path (not a shell command). Imports follow current upstream documentation:
`@earendil-works/pi-coding-agent` and `typebox`; older pi releases using other
package namespaces may require adaptation. No automatic interception is installed.

## Offline verification (synthetic, test-only)

```sh
uv pip install --python .agent-venv/bin/python -e '.[dev,mcp]'
.agent-venv/bin/python -m pytest tests/test_agent_integrations.py -q
JEV_TEST_CLI="$PWD/.agent-venv/bin/jev-route" node --test integrations/pi/process.test.mjs
jev-route --test-only-offline < request.json
```

`--test-only-offline` explicitly injects an httpx MockTransport into the REAL
Router and returns the first label with a synthetic one-hot distribution. It
never contacts a provider. Its output always has `test_only:true`. Never use it
for real decisions or interpret it as live quality, confidence, cost or latency.
The MCP test launches a real subprocess and performs initialize, list_tools,
call_tool and an invalid-input call using the official MCP client. Unit tests
also verify CLI errors/redaction and shared async timeout/cancellation behavior.
The Node tests exercise JSON stdin, timeout, abort and sanitized process errors.
The full Python suite passed (54 tests), including five bridge tests. Six Node
tests passed with `JEV_TEST_CLI` set, including an actual synthetic CLI decision;
without that variable this end-to-end case is explicitly skipped. A separate
Node 26 host harness loaded the actual TypeScript extension with real `typebox`,
captured `registerTool`, and invoked `execute` through the real installed CLI
using a test-only launcher. This is not a full pi host integration test or a
TypeScript static type-check. A built wheel was installed into a clean Python
3.12 environment and both console entrypoints were exercised from outside this
checkout (CLI and MCP initialize/list/call). MCP SDK 1.28.1 and 1.30.0 worked.
No live Jev/OpenAI inference was tested because keys were unavailable.

## Official references

- https://developers.openai.com/codex/customization/overview
- https://developers.openai.com/codex/mcp
- https://code.claude.com/docs/en/mcp
- https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/mcp/mcp-native-mcp
- https://docs.openclaw.ai/tools/skills
- https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md

Claude and OpenClaw documentation and the upstream pi extension document were
read directly. Codex/Hermes documentation fetches were blocked in this environment;
those configurations also use the supplied official-document context and local
Hermes MCP reference. Agent-host compatibility remains template-level until run
inside each actual agent.
