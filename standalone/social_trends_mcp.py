#!/usr/bin/env python3
"""
Standalone MCP server for the Social Trends agent.

Aggregates trend reports from 10 marketing blogs (Sprout Social, Hootsuite,
Later, etc.). Fetches article bodies and spawns a sub-agent (GPT-4o-mini)
to extract structured trends, audio tracks, and actionable tips.

Install:
    claude mcp add social-trends python /path/to/social_trends_mcp.py

Requires: OPENAI_API_KEY in .env (for the extraction sub-agent)

Usage from Claude Code:
    "What are the latest Instagram Reels trends?"
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

server = Server("social-trends")


@server.list_tools()
async def list_tools():
    return [Tool(
        name="social_trends",
        description="Aggregate trend reports from curated social media marketing blogs. "
                    "Extracts specific trend names, audio tracks, and tips using a sub-agent. "
                    "Supports: instagram, tiktok, reels, youtube shorts.",
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "Platform: instagram, tiktok, reels, youtube shorts"},
                "topic": {"type": "string", "description": "Optional topic filter"},
                "days": {"type": "integer", "description": "Lookback window in days (default 30)"},
                "limit": {"type": "integer", "description": "Max results to return (default 20)"},
            },
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from agentshub.agents.social_trends import run
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run(**arguments))
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
