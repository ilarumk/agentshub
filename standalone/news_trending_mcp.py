#!/usr/bin/env python3
"""
Standalone MCP server for the News Trending agent.

Fetches trending news articles by topic via Google News RSS.
Optional NewsAPI enrichment. Includes full article body fetching.

Install:
    claude mcp add news-trending python /path/to/news_trending_mcp.py

Usage from Claude Code:
    "What's in the news about AI this week?"
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

server = Server("news-trending")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="news_trending",
        description="Find trending news articles by topic. Uses Google News RSS with "
                    "optional NewsAPI enrichment and full article body fetching.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic or keyword to search"},
                "days": {"type": "integer", "description": "Lookback window in days (default 7)"},
                "limit": {"type": "integer", "description": "Max articles to return (default 20)"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.news_trending import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
