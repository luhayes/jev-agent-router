"""Optional MCP SDK stdio server. stdout is reserved for MCP JSON-RPC."""
import asyncio
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_agent_router import RouteRequest
from integrations.bridge import decide, options, router_context


async def serve(args):
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool

    server = Server("jev-agent-router")

    @server.list_tools()
    async def list_tools():
        return [Tool(name="jev_route", description="Select an allowed label using Jev confidence gating and an OpenAI fallback. Does not execute the selected action.", inputSchema=RouteRequest.model_json_schema())]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            if name != "jev_route":
                raise ValueError("unknown tool")
            # Validate locally to avoid SDK validation errors echoing sensitive input.
            RouteRequest.model_validate(arguments)
            async with router_context(args.test_only_offline) as router:
                result = await decide(router, arguments, timeout=args.timeout, test_only=args.test_only_offline)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))])
        except Exception:
            return CallToolResult(isError=True, content=[TextContent(type="text", text='{"error":"routing_failed_or_invalid_request"}')])

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    args = options()
    try:
        asyncio.run(serve(args))
    except ImportError:
        print("Install local project with the mcp extra to run this bridge.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("MCP server failed; check local configuration.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
