"""
Social Trends Agent — curated marketing blog aggregator + LLM extraction.

Three-step pipeline:
  1. DATA STEP:  Fan-out to 10 marketing blogs via Google News RSS
  2. FETCH STEP: Download the top 3 article bodies (real content)
  3. LLM STEP:   Sub-agent extracts structured trends from the articles
                 (format names, audio tracks, hashtags, platforms)

The sub-agent is internal to this agent — the orchestrator/caller doesn't
know or care that an LLM was used. Clean separation: data in, insights out.

Cost: ~$0.003 per run (GPT-4o-mini, ~2k tokens input).
"""

import json
import os
import re
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from collections import Counter
from agentshub.base import result, timer

NAME    = "social_trends"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; agentshub/0.1)"}
GNEWS   = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# Blogs with direct RSS → get real article URLs (preferred)
DIRECT_FEEDS = {
    "sproutsocial.com":    "https://sproutsocial.com/insights/feed/",
    "hootsuite.com":       "https://blog.hootsuite.com/feed/",
    "buffer.com":          "https://buffer.com/resources/feed/",
    "planable.io":         "https://planable.io/blog/feed/",
}

# Blogs without RSS → fall back to Google News site: query (titles only, no article fetch)
GNEWS_ONLY_SITES = [
    "later.com",
    "metricool.com",
    "scottsocialmarketing.com",
    "socialbee.com",
    "newengen.com",
    "rivaliq.com",
]

EXTRACT_PROMPT = """You are a trend extraction agent. Given article text from social media marketing blogs,
extract SPECIFIC, ACTIONABLE trends. Return valid JSON only.

For each trend found, extract:
- name: the trend name (e.g. "World Stop!", "Color Walk", "Split-Screen Carousels")
- type: one of "format", "audio", "hashtag", "challenge", "style", "strategy"
- platform: instagram | tiktok | both
- description: one sentence on what it is and why it works
- source: which blog/article it came from

Also extract trending audio tracks separately:
- song: track name
- artist: artist name
- mood: what type of content it fits (e.g. "emotional attachment", "feel-good progress")

Return format:
{
  "trends": [...],
  "audio": [...],
  "tips": ["one-line actionable tips found in the articles"]
}

ARTICLE TEXT:
"""


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_date(s: str) -> datetime | None:
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def _query_blog(site: str, topic: str) -> list[dict]:
    q   = f"site:{site} {topic}"
    url = GNEWS.format(q=urllib.parse.quote(q))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
    except Exception:
        return []

    try:
        root  = ET.fromstring(body)
        items = root.findall(".//item")
    except Exception:
        return []

    posts = []
    for item in items[:5]:
        title       = item.findtext("title", "")
        link        = item.findtext("link", "")
        pub_date    = item.findtext("pubDate", "")
        description = _strip_html(item.findtext("description", ""))
        posts.append({
            "title":     title.split(" - ")[0],
            "url":       link,
            "site":      site,
            "published": pub_date,
            "snippet":   description[:200],
            "_dt":       _parse_date(pub_date),
        })
    return posts


def _resolve_url(url: str) -> str:
    """Resolve Google News redirect URLs to actual article URLs."""
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import new_decoderv1
        result = new_decoderv1(url)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception:
        pass
    return ""


def _fetch_article_text(url: str, max_chars: int = 6000) -> str:
    """Fetch a URL and extract the trend-relevant portions of the article.
    Resolves Google News URLs first, then targets sections with trend keywords."""
    try:
        url = _resolve_url(url)
        if not url:
            return ""

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Strip scripts, styles, then tags
        html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

        # Extract windows around trend-related keywords instead of just the start
        KEYWORDS = ["reel", "trend", "carousel", "audio", "challenge", "format",
                     "hook", "viral", "creator", "shorts", "hashtag"]
        chunks = []
        seen_ranges = set()
        for kw in KEYWORDS:
            for m in re.finditer(kw, text, re.IGNORECASE):
                start = max(0, m.start() - 200)
                end   = min(len(text), m.start() + 400)
                # Avoid overlapping chunks
                bucket = start // 300
                if bucket not in seen_ranges:
                    seen_ranges.add(bucket)
                    chunks.append(text[start:end])

        if chunks:
            return "\n...\n".join(chunks[:15])[:max_chars]
        # Fallback: return middle portion of article
        mid = len(text) // 4
        return text[mid:mid + max_chars]
    except Exception:
        return ""


def _llm_extract(articles_text: str, query: str) -> dict | None:
    """Sub-agent: calls GPT-4o-mini to extract structured trends from article text."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract structured social media trend data. Return valid JSON only, no markdown."},
                {"role": "user",   "content": EXTRACT_PROMPT + articles_text},
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        return {"extraction_error": str(exc)}


def _log(msg):
    from datetime import datetime as _dt
    print(f"  [{_dt.now().strftime('%H:%M:%S')}] [social_trends] {msg}", flush=True)


def run(
    platform: str = "instagram",
    topic:    str = "trends",
    days:     int = 30,
    limit:    int = 20,
    extract:  bool = True,
) -> dict:
    """
    extract: if True, fetches top article bodies and runs LLM extraction sub-agent.
             Set False for fast mode (titles only, no LLM cost).
    """
    with timer() as t:
        query = f"{platform} {topic}".strip()

        sites = list(DIRECT_FEEDS.keys()) + GNEWS_ONLY_SITES
        _log(f"Fan-out to {len(sites)} blogs: {', '.join(sites[:4])}...")

        # STEP 1: Fan-out to all sources in parallel
        all_posts: list[dict] = []
        errors:    list[str]  = []

        def _query_direct_feed(site, feed_url, query):
            """Parse direct RSS, filter by keyword relevance."""
            try:
                import feedparser
                d = feedparser.parse(feed_url)
                keywords = query.lower().split()
                posts = []
                for e in d.entries[:30]:
                    title_l = e.title.lower()
                    if any(k in title_l for k in keywords):
                        posts.append({
                            "title":     e.title,
                            "url":       e.link,
                            "site":      site,
                            "published": e.get("published", ""),
                            "snippet":   _strip_html(e.get("summary", ""))[:200],
                            "_dt":       _parse_date(e.get("published", "")),
                        })
                return posts
            except Exception:
                return []

        workers = len(DIRECT_FEEDS) + len(GNEWS_ONLY_SITES)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {}
            # Direct RSS feeds (preferred — real URLs)
            for site, feed_url in DIRECT_FEEDS.items():
                futures[pool.submit(_query_direct_feed, site, feed_url, query)] = site
            # Google News fallback
            for site in GNEWS_ONLY_SITES:
                futures[pool.submit(_query_blog, site, query)] = site

            for fut in as_completed(futures):
                site = futures[fut]
                try:
                    posts = fut.result()
                    all_posts.extend(posts)
                except Exception as exc:
                    errors.append(f"{site}: {exc}")

        # Filter by recency
        cutoff_ts = datetime.now().astimezone().timestamp() - days * 86400
        recent = [
            p for p in all_posts
            if p.get("_dt") and p["_dt"].timestamp() >= cutoff_ts
        ]
        recent.sort(key=lambda p: p["_dt"], reverse=True)
        for p in recent:
            p.pop("_dt", None)
            p["published"] = p["published"][:25]

        top = recent[:limit]
        site_counts = Counter(p["site"] for p in top)
        _log(f"  ← {len(top)} posts from {len(site_counts)} blogs (filtered to last {days} days)")

        # STEP 2 + 3: Fetch articles + LLM extraction (sub-agent)
        extracted = None
        if extract and top:
            # Fetch top 3 most recent articles
            _log(f"Fetching top 3 article bodies for extraction...")
            articles_text_parts = []
            for post in top[:3]:
                _log(f"  GET {post['url'][:70]}...")
                text = _fetch_article_text(post["url"])
                if text:
                    _log(f"  ← {len(text)} chars extracted from {post['site']}")
                    articles_text_parts.append(
                        f"--- SOURCE: {post['site']} | {post['title']} ---\n{text[:3000]}"
                    )

            if articles_text_parts:
                combined = "\n\n".join(articles_text_parts)
                _log(f"Spawning sub-agent → GPT-4o-mini (extracting trends from {len(combined)} chars)")
                extracted = _llm_extract(combined, query)
                if extracted and "trends" in extracted:
                    _log(f"  ← sub-agent returned {len(extracted.get('trends',[]))} trends, {len(extracted.get('audio',[]))} audio, {len(extracted.get('tips',[]))} tips")

        # Build insights
        insights = [
            {
                "type":    "coverage",
                "finding": f"{len(top)} posts from {len(site_counts)} blogs about '{query}'",
                "by_site": dict(site_counts.most_common()),
            },
        ]

        if extracted and "trends" in extracted:
            insights.append({
                "type":    "extracted trends",
                "finding": f"{len(extracted['trends'])} specific trends extracted from article content",
                "trends":  extracted["trends"],
            })
        if extracted and "audio" in extracted:
            insights.append({
                "type":    "trending audio",
                "finding": f"{len(extracted['audio'])} trending audio tracks identified",
                "audio":   extracted["audio"],
            })
        if extracted and "tips" in extracted:
            insights.append({
                "type":    "actionable tips",
                "finding": "; ".join(extracted["tips"][:5]),
            })

        return result(
            name       = NAME,
            status     = "SUCCESS" if top else "PARTIAL",
            mode       = f"LIVE — {len(DIRECT_FEEDS) + len(GNEWS_ONLY_SITES)} blogs + LLM extraction" if extracted else
                         f"LIVE — {len(DIRECT_FEEDS) + len(GNEWS_ONLY_SITES)} blogs (no extraction)",
            duration_s = t.elapsed,
            insights   = insights,
            posts      = top,
            extracted  = extracted,
            errors     = errors,
            query      = query,
        )
