"""Lazy, async-only framework tools. Each tool returns Decision JSON.

No selected tool, agent, skill, shell command, or label is executed here.
Framework telemetry configuration belongs to the host application.
"""

import asyncio
from pydantic import BaseModel, ConfigDict
from . import Router, RouteRequest

_DESCRIPTION = "Select an allowed route using Jev confidence and fallback; returns decision JSON, does not execute the route."


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str


def _function(router: Router, criteria: dict[str, str], instructions: str):
    validated = RouteRequest(state="", criteria=criteria, instructions=instructions)

    async def route(state: str) -> str:
        """Select a route for the supplied text; return decision JSON."""
        return (
            await router.route(state, validated.criteria, instructions=validated.instructions)
        ).model_dump_json()

    return route


def langchain_tool(
    router: Router,
    criteria: dict[str, str],
    *,
    instructions: str = "Select the best route",
    name: str = "jev_route",
):
    """Return langchain-core StructuredTool; use await tool.ainvoke(...)."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError("Install jev-agent-router[langchain]") from exc
    return StructuredTool.from_function(
        coroutine=_function(router, criteria, instructions),
        name=name,
        description=_DESCRIPTION,
        args_schema=_Input,
    )


def crewai_tool(
    router: Router,
    criteria: dict[str, str],
    *,
    instructions: str = "Select the best route",
    name: str = "jev_route",
):
    """Return CrewAI BaseTool; only async arun/_arun is supported."""
    try:
        from crewai.tools import BaseTool
    except ImportError as exc:
        raise ImportError("Install jev-agent-router[crewai]") from exc
    route = _function(router, criteria, instructions)

    class JevTool(BaseTool):
        def _run(self, state: str) -> str:
            raise NotImplementedError("Jev router is async-only; use await tool.arun(state=...)")

        async def _arun(self, state: str) -> str:
            return await route(state)

    return JevTool(name=name, description=_DESCRIPTION, args_schema=_Input)


def pydantic_ai_tool(
    router: Router,
    criteria: dict[str, str],
    *,
    instructions: str = "Select the best route",
    name: str = "jev_route",
):
    """Return Pydantic AI Tool for Agent(tools=[tool])."""
    try:
        from pydantic_ai import Tool
    except ImportError as exc:
        raise ImportError("Install jev-agent-router[pydantic-ai]") from exc
    return Tool(
        _function(router, criteria, instructions), takes_ctx=False, name=name, description=_DESCRIPTION
    )


def autogen_tool(
    router: Router,
    criteria: dict[str, str],
    *,
    instructions: str = "Select the best route",
    name: str = "jev_route",
):
    """Return AutoGen FunctionTool, linking its cancellation token to routing."""
    try:
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
    except ImportError as exc:
        raise ImportError("Install jev-agent-router[autogen]") from exc
    route = _function(router, criteria, instructions)

    async def run(state: str, cancellation_token: CancellationToken) -> str:
        task = asyncio.create_task(route(state))
        cancellation_token.link_future(task)
        return await task

    return FunctionTool(run, name=name, description=_DESCRIPTION)
