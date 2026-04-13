#!/usr/bin/env python3
"""
Standalone MCP server for the Wikipedia Spike agent.

Detects Wikipedia article pageview spikes — a leading indicator for
cultural, celebrity, and event-driven trends.

Install:
    claude mcp add wikipedia-spike python /path/to/wikipedia_spike_mcp.py

Usage from Claude Code:
    "Is the Wikipedia page for Taylor Swift spiking?"
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

server = Server("wikipedia-spike")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="wikipedia_spike",
        description="Detect Wikipedia article pageview spikes. Returns articles whose "
                    "pageviews spiked vs their baseline. Leading indicator for cultural "
                    "and event-driven trends.",
        inputSchema={
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}, "description": "List of Wikipedia article titles to check"},
                "days": {"type": "integer", "description": "Lookback window in days (default 7)"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.wikipedia_spike import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
