"""
Agent registry.

Each agent is a module with a `run(**kwargs) -> AgentResult` function.
The registry maps an agent name to the module's run function + metadata,
so the MCP server and orchestrator can discover and call them uniformly.
"""

from importlib import import_module
from typing import Callable, TypedDict


class AgentMeta(TypedDict):
    name:        str
    module:      str
    description: str
    params:      dict  # JSON-schema-like description of accepted params


REGISTRY: list[AgentMeta] = [
    {
        "name":        "rising_search",
        "module":      "agentshub.agents.rising_search",
        "description": "Returns ALL nationally rising and popular Google search terms this week. "
                       "No filtering — returns the full list (~30 rising + ~25 popular terms). "
                       "YOU interpret which terms relate to the user's topic. Call this to get "
                       "the national search pulse, then pick out relevant terms in your answer.",
        "params": {},
    },
    {
        "name":        "wikipedia_spike",
        "module":      "agentshub.agents.wikipedia_spike",
        "description": "Detect Wikipedia article pageview spikes. A leading indicator for "
                       "cultural, celebrity, and event-driven trends. Returns articles whose "
                       "pageviews spiked vs their baseline.",
        "params": {
            "topics":     {"type": "array", "description": "List of Wikipedia article titles to check"},
            "days":       {"type": "integer", "description": "Lookback window in days (default 7)"},
        },
    },
    {
        "name":        "news_trending",
        "module":      "agentshub.agents.news_trending",
        "description": "Find trending news articles by topic. Uses Google News RSS (free, unlimited) "
                       "with optional NewsAPI enrichment. Editorial coverage is a 1-2 week leading "
                       "indicator for TikTok/Instagram content trends.",
        "params": {
            "topic":      {"type": "string", "description": "Topic or keyword to search"},
            "days":       {"type": "integer", "description": "Lookback window in days (default 7)"},
            "limit":      {"type": "integer", "description": "Max articles to return (default 20)"},
        },
    },
    {
        "name":        "youtube_shorts",
        "module":      "agentshub.agents.youtube_shorts",
        "description": "Find trending YouTube videos in a topic or category. Can filter for "
                       "short-form content (<60s) as a proxy for TikTok trends. Requires "
                       "YOUTUBE_API_KEY env var.",
        "params": {
            "topic":      {"type": "string", "description": "Topic keyword to search"},
            "region":     {"type": "string", "description": "ISO region code (default US)"},
            "shorts_only":{"type": "boolean", "description": "Filter to videos under 60 seconds"},
        },
    },
    {
        "name":        "social_trends",
        "module":      "agentshub.agents.social_trends",
        "description": "Aggregate trend reports from curated social media marketing blogs "
                       "(Sprout Social, Hootsuite, Later, Planable, Metricool, etc.). "
                       "These blogs publish weekly Instagram/TikTok/Reels trend roundups — "
                       "a legal proxy for closed-platform trends. Returns recent posts ranked "
                       "by publish date.",
        "params": {
            "platform":   {"type": "string", "description": "Platform: instagram, tiktok, reels, youtube shorts"},
            "topic":      {"type": "string", "description": "Optional topic filter (e.g. 'audio', 'skincare')"},
            "days":       {"type": "integer", "description": "Lookback window in days (default 30)"},
            "limit":      {"type": "integer", "description": "Max results to return (default 20)"},
        },
    },
    {
        "name":        "instagram_trends",
        "module":      "agentshub.agents.instagram_trends",
        "description": "Discover trending Instagram content for any topic. Searches hashtags "
                       "via Apify, finds accounts with viral posts (100K+ views or 10K+ likes), "
                       "aggregates trending hashtags, hooks, content types, and engagement patterns. "
                       "Requires APIFY_TOKEN.",
        "params": {
            "topic":        {"type": "string", "description": "Topic to search (e.g. 'skincare', 'fitness', 'cooking')"},
            "hashtags":     {"type": "string", "description": "Comma-separated hashtags (auto-generated from topic if empty)"},
            "max_accounts": {"type": "integer", "description": "Max accounts to check for viral content (default 20)"},
        },
    },
    {
        "name":        "search_console",
        "module":      "agentshub.agents.search_console",
        "description": "Pull Google Search Console data for any site. Returns top queries by "
                       "impressions, CTR, position, and identifies quick-win SEO opportunities "
                       "(high impressions, low CTR). Requires GSC_SITE_URL or site_url parameter.",
        "params": {
            "site_url":    {"type": "string", "description": "Site URL (e.g. https://example.com). Uses GSC_SITE_URL env var if empty."},
            "days":        {"type": "integer", "description": "Lookback window in days (default 30)"},
        },
    },
    {
        "name":        "bbc_news",
        "module":      "agentshub.agents.bbc_news",
        "description": "Search BBC News articles by topic via BigQuery public dataset. "
                       "Returns article titles, descriptions, body previews, and category breakdown.",
        "params": {
            "topic":  {"type": "string", "description": "Topic or keywords to search (e.g. 'artificial intelligence')"},
            "limit":  {"type": "integer", "description": "Max articles to return (default 10)"},
        },
    },
    {
        "name":        "patent_search",
        "module":      "agentshub.agents.patent_search",
        "description": "Search 90M+ patent publications by keyword. Returns filings, top assignees, "
                       "filing velocity over time, and country breakdown. The supervisor can call this "
                       "multiple times with different keywords to expand the search.",
        "params": {
            "keywords":    {"type": "string", "description": "Search terms (e.g. 'quantum computing', 'AI chips')"},
            "years_back":  {"type": "integer", "description": "Years of filing history to include (default 5)"},
            "limit":       {"type": "integer", "description": "Max patents to return (default 15)"},
        },
    },
    {
        "name":        "bigquery_analyst",
        "module":      "agentshub.agents.bigquery_analyst",
        "description": "Execute SQL against any BigQuery public dataset, or inspect table schemas. "
                       "Use action='schema' with a dataset name to see tables and columns. "
                       "Use action='query' with SQL to run a query. Only SELECT queries allowed.",
        "params": {
            "query":   {"type": "string", "description": "SQL query to execute (SELECT only)"},
            "dataset": {"type": "string", "description": "Dataset to inspect (e.g. 'bigquery-public-data.google_trends')"},
            "action":  {"type": "string", "description": "'query' to run SQL, 'schema' to list tables/columns"},
            "limit":   {"type": "integer", "description": "Max rows to return (default 20)"},
        },
    },
    {
        "name":        "site_security",
        "module":      "agentshub.agents.site_security",
        "description": "Scan a website for common security misconfigurations. Checks SSL, "
                       "security headers, WordPress vulnerabilities, exposed sensitive files, "
                       "server info leakage. Public HTTP requests only — no authentication or "
                       "intrusive testing. Returns a security grade (A-F).",
        "params": {
            "url":    {"type": "string", "description": "Website URL to scan (e.g. https://example.com)"},
            "checks": {"type": "string", "description": "Comma-separated: ssl, headers, wordpress, files, server, all (default: all)"},
        },
    },
]


def get_run(name: str) -> Callable:
    for meta in REGISTRY:
        if meta["name"] == name:
            mod = import_module(meta["module"])
            return mod.run
    raise KeyError(f"Unknown agent: {name}")


def list_agents() -> list[AgentMeta]:
    return list(REGISTRY)
