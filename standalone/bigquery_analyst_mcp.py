#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
import asyncio, json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from agentshub.agents import REGISTRY, get_run

AGENT_NAME = "bigquery_analyst"
server = Server(AGENT_NAME)

@server.list_tools()
async def list_tools():
    meta = next(m for m in REGISTRY if m["name"] == AGENT_NAME)
    props = {}
    for pname, pdesc in meta["params"].items():
        props[pname] = {"type": pdesc.get("type", "string"), "description": pdesc.get("description", "")}
    return [Tool(name=meta["name"], description=meta["description"], inputSchema={"type": "object", "properties": props})]

@server.call_tool()
async def call_tool(name, arguments):
    run_fn = get_run(name)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run_fn(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
