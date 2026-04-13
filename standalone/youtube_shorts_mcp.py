#!/usr/bin/env python3
"""
Standalone MCP server for the YouTube Shorts agent.

Finds trending YouTube videos by topic. Can filter for short-form
content (<60s) as a proxy for TikTok trends.

Install:
    claude mcp add youtube-shorts python /path/to/youtube_shorts_mcp.py

Requires: YOUTUBE_API_KEY in .env

Usage from Claude Code:
    "What YouTube Shorts about cooking are trending?"
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

server = Server("youtube-shorts")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="youtube_shorts",
        description="Find trending YouTube videos by topic. Can filter to short-form "
                    "content under 60 seconds. Requires YOUTUBE_API_KEY.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic keyword to search"},
                "region": {"type": "string", "description": "ISO region code (default US)"},
                "shorts_only": {"type": "boolean", "description": "Filter to videos under 60 seconds"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.youtube_shorts import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
