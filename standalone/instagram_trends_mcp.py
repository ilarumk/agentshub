#!/usr/bin/env python3
"""
Standalone MCP server for the Instagram Trends agent.

Discovers trending Instagram content for any topic via Apify.
Searches hashtags, finds viral posts, aggregates trends.

Install:
    claude mcp add instagram-trends python /path/to/instagram_trends_mcp.py

Requires: APIFY_TOKEN in .env

Usage from Claude Code:
    "What skincare content is going viral on Instagram?"
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

server = Server("instagram-trends")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="instagram_trends",
        description="Discover trending Instagram content for any topic. Searches hashtags "
                    "via Apify, finds viral posts (100K+ views or 10K+ likes), aggregates "
                    "trending hashtags, hooks, and engagement patterns.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic to search (e.g. skincare, fitness, cooking)"},
                "hashtags": {"type": "string", "description": "Comma-separated hashtags (auto-generated if empty)"},
                "max_accounts": {"type": "integer", "description": "Max accounts to check (default 20)"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.instagram_trends import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
