# agentshub

A collection of AI agents for trend research, news analysis, and content intelligence. Each agent can run standalone (as an MCP server) or together through an orchestrator that routes queries to the right agents automatically.

## Agents

| Agent | Data Source | What it does | Standalone MCP |
|---|---|---|---|
| `rising_search` | BigQuery Google Trends | Nationally rising + popular search terms across 210 US DMAs | `standalone/rising_search_mcp.py` |
| `news_trending` | Google News RSS | Trending articles by topic with full article body fetching | `standalone/news_trending_mcp.py` |
| `social_trends` | 10 marketing blogs | Trend extraction from Sprout Social, Hootsuite, Later, etc. Spawns sub-agent for structured extraction | `standalone/social_trends_mcp.py` |
| `wikipedia_spike` | Wikipedia Pageview API | Detects pageview spikes — leading indicator for cultural trends | `standalone/wikipedia_spike_mcp.py` |
| `youtube_shorts` | YouTube Data API | Trending videos by topic, filterable to shorts (<60s) | `standalone/youtube_shorts_mcp.py` |
| `instagram_trends` | Apify Instagram Scraper | Discovers viral Instagram content by topic — hashtags, hooks, engagement patterns | `standalone/instagram_trends_mcp.py` |
| `search_console` | Google Search Console API | Top queries, impressions, CTR, position. Identifies quick-win SEO opportunities | `standalone/search_console_mcp.py` |
| `bbc_news` | BigQuery BBC News | Searches BBC News articles by topic — titles, descriptions, body previews | `standalone/bbc_news_mcp.py` |
| `patent_search` | BigQuery Google Patents | Searches 90M+ patents by keyword — filings, assignees, velocity, countries | `standalone/patent_search_mcp.py` |
| `bigquery_analyst` | Any BigQuery public dataset | Runs SQL queries or inspects table schemas. SELECT only. | `standalone/bigquery_analyst_mcp.py` |
| `site_security` | Public HTTP requests | Scans websites for security issues — SSL, headers, WordPress vulns, exposed files. Grades A-F. | `standalone/site_security_mcp.py` |

### Example: site_security agent

```
> scan the security of example-shop.com

agents firing:
  → site_security(url='https://www.example-shop.com')
  [21:22:10] Scanning https://www.example-shop.com
  [21:22:11]   ✓ SSL valid, expires 2026-06-20 (68 days)
  [21:22:14] Checking security headers...
  [21:22:14]   0/7 headers present, 7 missing
  [21:22:14] Checking for WordPress...
  [21:22:16]   ⚠ EXPOSED: /wp-content/debug.log
  [21:22:20] Scan complete: 0 critical, 8 warnings, 1 info
  [21:22:20] Grade: C

Key findings:
  ✓ SSL valid (Let's Encrypt, 68 days remaining)
  ✓ HTTPS redirect working
  ✗ 7/7 security headers missing (HSTS, CSP, X-Frame-Options, etc.)
  ✗ Server header exposes software version
  ✗ /wp-content/debug.log publicly accessible
```

## Install from PyPI

```bash
pip install agentshub-ai              # core agents
pip install agentshub-ai[instagram]   # + Instagram via Apify
pip install agentshub-ai[seo]         # + Google Search Console
pip install agentshub-ai[all]         # everything

# Register as MCP server in Claude Code
claude mcp add agentshub agentshub-mcp
```

## Quick start (from source)

```bash
git clone https://github.com/ilarumk/agentshub.git
cd agentshub
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"

# Add your keys
cp .env.example .env
# Edit .env with your GOOGLE_CLOUD_PROJECT, OPENAI_API_KEY, etc.

# Run the interactive chat (supervisor routes to agents automatically)
python chat.py
```

## Three ways to use

### 1. Interactive chat — supervisor decides which agents to call
```bash
python chat.py

> what's trending in AI advertising this week?
# → fires rising_search + news_trending + social_trends automatically
```

### 2. Parallel demo — sequential vs parallel with timing
```bash
python demo.py
# → runs 3 agents sequential, then parallel, shows speedup
```

### 3. Standalone MCP — use one agent from Claude Code
```bash
# Register a single agent
claude mcp add rising-search python standalone/rising_search_mcp.py

# Or register all agents at once
claude mcp add agentshub python -m agentshub.mcp_server
```

## Architecture

```
User query
    │
    ▼
Orchestrator / Supervisor (GPT-4o-mini)
    │ reads query → decides which agents to call
    │
    ├─→ rising_search     [BigQuery — no LLM]
    ├─→ news_trending     [RSS + web fetch — no LLM]
    ├─→ social_trends     [10 blogs + sub-agent GPT-4o-mini]
    ├─→ wikipedia_spike   [Pageview API — no LLM]
    ├─→ youtube_shorts    [YouTube API — no LLM]
    ├─→ instagram_trends  [Apify — no LLM]
    ├─→ search_console    [GSC API — no LLM]
    ├─→ bbc_news          [BigQuery — no LLM]
    ├─→ patent_search     [BigQuery — no LLM]
    ├─→ bigquery_analyst  [BigQuery — any dataset, any SQL]
    └─→ site_security    [HTTP checks — no auth needed]
    │
    ▼
Synthesizer (GPT-4o-mini) → final response
```

## Adding a new agent

1. Create `agentshub/agents/your_agent.py` with a `run(**kwargs) -> dict` function
2. Add entry to `REGISTRY` in `agentshub/agents/__init__.py`
3. (Optional) Create `standalone/your_agent_mcp.py` for standalone use
4. The orchestrator, chat, and MCP server pick it up automatically

## Stack

- **Orchestration**: Custom fan-out/fan-in with ThreadPoolExecutor
- **Supervisor**: GPT-4o-mini via OpenAI function calling
- **Data agents**: BigQuery, Google News RSS, Wikipedia API, YouTube API
- **Sub-agent extraction**: GPT-4o-mini for structured trend extraction
- **MCP**: Model Context Protocol for standalone agent access
- **Web fetch**: Parallel article fetching with blocking/paywall handling

## Requirements

- Python 3.11+
- Google Cloud project with BigQuery access (for rising_search)
- OpenAI API key (for supervisor + social_trends sub-agent)
- YouTube API key (for youtube_shorts, optional)
- Apify API token (for instagram_trends, optional)
- Google Search Console access (for search_console, optional)
