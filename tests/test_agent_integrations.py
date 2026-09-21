"""Agent bridges use synthetic transports only; never evidence of live quality."""
import json
import asyncio
import pytest
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUEST = {"state": "synthetic test input", "criteria": {"a": "First", "b": "Second"}, "instructions": "Select a route"}


def cli(payload, *args):
    return subprocess.run([sys.executable, str(ROOT / "integrations/cli.py"), *args], input=payload, text=True, capture_output=True, timeout=15, cwd=ROOT)


def test_cli_offline_fixture_uses_core():
    result = cli(json.dumps(REQUEST), "--test-only-offline")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["test_only"] is True
    assert data["decision"]["label"] == "a"
    assert data["decision"]["origin"] == "jev"
    assert data["decision"]["reason"] == "confident"


def test_cli_missing_configuration_is_not_invalid_request():
    import os
    env = {k: v for k, v in os.environ.items() if k not in {"TYPESAFE_API_KEY", "OPENAI_API_KEY", "JEV_FALLBACK_MODEL"}}
    result = subprocess.run([sys.executable, str(ROOT / "integrations/cli.py")], input=json.dumps(REQUEST), text=True, capture_output=True, timeout=15, env=env)
    assert result.returncode == 3
    assert json.loads(result.stdout)["error"] == "routing_failed_check_configuration"


def test_cli_rejects_invalid_json_without_echoing_secrets():
    result = cli('{"secret":"DO_NOT_ECHO"', "--test-only-offline")
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "invalid_request"
    assert "DO_NOT_ECHO" not in result.stdout + result.stderr


@pytest.mark.asyncio
async def test_bridge_timeout_and_cancellation_propagate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("integration_bridge", ROOT / "integrations/bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)

    class SlowRouter:
        cancelled = False

        async def route(self, *args, **kwargs):
            try:
                await asyncio.sleep(20)
            finally:
                self.cancelled = True

    slow = SlowRouter()
    with pytest.raises(TimeoutError):
        await bridge.decide(slow, REQUEST, timeout=0.01)
    assert slow.cancelled
    slow = SlowRouter()
    task = asyncio.create_task(bridge.decide(slow, REQUEST))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert slow.cancelled



@pytest.mark.asyncio
async def test_real_mcp_stdio_synthetic_fixture():
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "integrations/mcp_server.py"), "--test-only-offline"])
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [t.name for t in tools.tools] == ["jev_route"]
                result = await session.call_tool("jev_route", REQUEST)
                data = json.loads(result.content[0].text)
                assert not result.isError
                assert data["test_only"] is True
                assert data["decision"]["label"] == "a"
                invalid = await session.call_tool("jev_route", {"state": "DO_NOT_ECHO"})
                assert invalid.isError
                assert "DO_NOT_ECHO" not in str(invalid)
