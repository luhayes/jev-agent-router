import asyncio
import importlib.util
import json
import subprocess
import sys
import httpx
import pytest
from jev_agent_router import Router


def test_adapters_exist_and_lazy():
    assert importlib.util.find_spec("jev_agent_router.adapters") is not None
    subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import jev_agent_router.adapters; assert not any(x in sys.modules for x in ["langchain_core", "crewai", "pydantic_ai", "autogen_core"])',
        ],
        check=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["langchain", "crewai", "pydantic_ai", "autogen"])
async def test_real_framework_tool(framework):
    from jev_agent_router import adapters

    dependency = {
        "langchain": "langchain_core",
        "crewai": "crewai",
        "pydantic_ai": "pydantic_ai",
        "autogen": "autogen_core",
    }[framework]
    pytest.importorskip(dependency)

    async def fallback(request):
        return {"label": "billing"}

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        router = Router(api_key="key", fallback=fallback, client=client)
        tool = getattr(adapters, framework + "_tool")(router, {"billing": "Payments"})
        if framework == "langchain":
            value = await tool.ainvoke({"state": "invoice"})
        elif framework == "crewai":
            value = await tool.arun(state="invoice")
            with pytest.raises(NotImplementedError):
                tool._run(state="invoice")
        elif framework == "pydantic_ai":
            from pydantic_ai import Agent
            from pydantic_ai.models.test import TestModel

            agent = Agent(TestModel(), tools=[tool])
            result = await agent.run("invoice")
            assert "billing" in str(result.output)
            value = await tool.function(state="invoice")
        else:
            from autogen_core import CancellationToken

            value = await tool.run_json({"state": "invoice"}, CancellationToken())
        assert json.loads(value)["label"] == "billing"
        assert json.loads(value)["confidence"] is None


@pytest.mark.asyncio
async def test_autogen_cancellation():
    pytest.importorskip("autogen_core")
    from autogen_core import CancellationToken
    from jev_agent_router.adapters import autogen_tool

    started = asyncio.Event()

    async def slow(request):
        started.set()
        await asyncio.sleep(30)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:

        async def fallback(request):
            return {"label": "billing"}

        tool = autogen_tool(Router(api_key="key", fallback=fallback, client=client), {"billing": "Payments"})
        token = CancellationToken()
        task = asyncio.create_task(tool.run_json({"state": "invoice"}, token))
        await started.wait()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
