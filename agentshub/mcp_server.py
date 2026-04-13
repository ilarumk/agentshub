"""
MCP server for agentshub.

Exposes every agent in the registry as an MCP tool. Connect from Claude Desktop,
Slack, VS Code, or any MCP-compatible client.

Run:
    agentshub-mcp
or:
    python -m agentshub.mcp_server
"""

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentshub.agents import REGISTRY, get_run

# Load .env from package root if present
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PACKAGE_DIR, ".env"))

server = Server("agentshub")


def _agent_meta_to_tool(meta: dict) -> Tool:
    properties: dict[str, Any] = {}
    for pname, pdesc in meta["params"].items():
        ptype = pdesc.get("type", "string")
        # Map our simple types to JSON schema types
        if ptype == "integer":
            json_type = "integer"
        elif ptype == "boolean":
            json_type = "boolean"
        elif ptype == "array":
            json_type = "array"
        else:
            json_type = "string"

        prop: dict[str, Any] = {
            "type":        json_type,
            "description": pdesc.get("description", ""),
        }
        if json_type == "array":
            prop["items"] = {"type": "string"}
        properties[pname] = prop

    return Tool(
        name        = meta["name"],
        description = meta["description"],
        inputSchema = {
            "type":       "object",
            "properties": properties,
        },
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [_agent_meta_to_tool(m) for m in REGISTRY]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        run_fn = get_run(name)
    except KeyError:
        return [TextContent(type="text", text=f"Unknown agent: {name}")]

    # Run the (sync) agent in a thread so we don't block the event loop
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run_fn(**arguments))

    # Return both a structured JSON dump and a one-line summary at the top
    summary = f"[{result.get('status','?')}] {result.get('agent','?')} — {result.get('mode','')}"
    body    = json.dumps(result, indent=2, default=str)
    return [TextContent(type="text", text=f"{summary}\n\n{body}")]


async def _async_main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
