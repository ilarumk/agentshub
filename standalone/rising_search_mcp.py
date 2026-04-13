#!/usr/bin/env python3
"""
Standalone MCP server for the Rising Search agent.

Queries BigQuery Google Trends public dataset for nationally rising
and popular search terms. Updated daily, covers 210 US DMAs.

Install:
    claude mcp add rising-search python /path/to/rising_search_mcp.py

Usage from Claude Code:
    "What search terms are rising nationally this week?"
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("rising-search")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="rising_search",
        description="Returns nationally rising and popular Google search terms this week. "
                    "Queries BigQuery Google Trends public dataset across 210 US DMAs.",
        inputSchema={"type": "object", "properties": {}},
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.rising_search import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run)
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
