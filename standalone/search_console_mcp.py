#!/usr/bin/env python3
"""
Standalone MCP server for the Search Console agent.

Pulls Google Search Console data: top queries, impressions, CTR,
position. Identifies quick-win SEO opportunities.

Install:
    claude mcp add search-console python /path/to/search_console_mcp.py

Requires: GSC_SITE_URL in .env + Google ADC with Search Console access

Usage from Claude Code:
    "What are the top search queries for my site?"
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

server = Server("search-console")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="search_console",
        description="Pull Google Search Console data for any site. Returns top queries "
                    "by impressions, CTR, position. Identifies quick-win SEO opportunities.",
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {"type": "string", "description": "Site URL (e.g. https://example.com)"},
                "days": {"type": "integer", "description": "Lookback window in days (default 30)"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.search_console import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
