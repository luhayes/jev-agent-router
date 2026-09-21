# Install the same skill in different agents

This package is local/unpublished. From its checkout, install the tool first:
```text
uv venv .agent-venv
uv pip install --python .agent-venv/bin/python -e '.[mcp]'
```
On Windows use the environment's Scripts/python.exe. Discover the installed
jev-route / jev-route-mcp executable paths and configure private credentials
TYPESAFE_API_KEY, OPENAI_API_KEY, JEV_FALLBACK_MODEL. Do not copy keys into the skill.
MCP registration and skill discovery are separate operations.

Copy the ENTIRE `skills/jev-router` directory (including references and scripts)
to a reviewed skill location below, only with owner approval. Do not overwrite
an existing skill. Restart/reload the host as required. Paths are conventional
project/user locations, not a claim of automatic installation or universal versions.

| Host | Suggested skill directory | Execution |
|---|---|---|
| Codex | .agents/skills/jev-router | Registered MCP tool or CLI |
| Claude Code | .claude/skills/jev-router | Registered MCP tool or CLI |
| OpenClaw | skills/jev-router in its selected workspace | CLI or separately configured tool |
| pi coding agent | .pi/skills/jev-router | CLI; native extension is an alternative |
| Hermes | ~/.hermes/skills/jev-router in the intended profile | Native MCP tool or CLI |

Hermes profiles have separate skill roots: do not write another profile without
permission. Hermes may filter MCP environments; forward credentials privately,
not by assuming shell exports will reach the MCP subprocess.

Existing repository `integrations/configs/` has MCP templates, and
`integrations/README.md` documents the transport layer. These repository paths
are not inside the copied skill. Keep those setup docs available from the checkout.
For OpenClaw prefer THIS complete skill over the older minimal `jev-route` skill;
do not enable both workflows. The older directory remains for compatibility.

## Host acceptance checklist

1. Host discovers jev-router and can load SKILL.md plus referenced files.
2. Correct MCP schema or CLI executable is available in that host's environment.
3. Offline file-runner smoke returns test_only=true without provider calls.
4. Only after approval and private key configuration, harmless live input returns
   test_only=false and an allowed label. No action is dispatched automatically.

Current verification: skill structure and actual CLI offline smoke automated.
Full discovery/invocation inside all five agents is not yet verified. A copied
skill alone is not evidence of host compatibility.

References: https://developers.openai.com/codex/skills ;
https://code.claude.com/docs/en/skills ; https://docs.openclaw.ai/tools/skills ;
https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs ;
https://hermes-agent.nousresearch.com/docs/ .
