"""
News Trending Agent — Google News RSS (free, unlimited).

Optional NewsAPI.org enrichment if NEWSAPI_KEY is set.

Returns recent articles for a topic, ranked by recency.
Editorial coverage typically leads social trends by 1-2 weeks.
"""

import os
import json
import time as time_module
import urllib.request
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from agentshub.base import result, timer

NAME      = "news_trending"
HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; agentshub/0.1)"}
NEWSAPI   = "https://newsapi.org/v2/everything"
GNEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s).strip()


def _fetch_google_news(topic: str, limit: int = 30) -> list[dict]:
    url = GNEWS_RSS.format(q=urllib.parse.quote(topic))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = resp.read()

    root  = ET.fromstring(body)
    items = root.findall(".//item")
    articles = []
    for item in items[:limit]:
        title       = item.findtext("title", "")
        link        = item.findtext("link", "")
        pub_date    = item.findtext("pubDate", "")
        description = _strip_html(item.findtext("description", ""))
        source      = item.find("source")
        source_name = source.text if source is not None else ""
        articles.append({
            "title":   title,
            "url":     link,
            "source":  source_name,
            "published": pub_date,
            "snippet": description[:200],
        })
    return articles


def _fetch_newsapi(topic: str, days: int, limit: int) -> list[dict]:
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return []
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "q":        topic,
        "from":     from_date,
        "sortBy":   "publishedAt",
        "language": "en",
        "pageSize": str(limit),
        "apiKey":   api_key,
    }
    url = f"{NEWSAPI}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return [
            {
                "title":     a["title"],
                "url":       a["url"],
                "source":    a.get("source", {}).get("name", ""),
                "published": a.get("publishedAt", ""),
                "snippet":   (a.get("description") or "")[:200],
            }
            for a in data.get("articles", [])
        ]
    except Exception:
        return []


def _theme_keywords(articles: list[dict]) -> list[tuple[str, int]]:
    """Extract recurring multi-word phrases from titles — proxy for emerging themes."""
    import re
    stopwords = {
        "the", "a", "an", "of", "to", "in", "for", "on", "with", "and", "or",
        "is", "are", "was", "were", "this", "that", "from", "by", "at", "as",
        "best", "new", "top", "your", "you", "how", "why", "what", "be", "have",
    }
    counter = Counter()
    for a in articles:
        words = re.findall(r"[a-z]+", a["title"].lower())
        words = [w for w in words if w not in stopwords and len(w) > 3]
        counter.update(words)
    return counter.most_common(8)


def _log(msg):
    from datetime import datetime as _dt
    print(f"  [{_dt.now().strftime('%H:%M:%S')}] [news_trending] {msg}", flush=True)


def run(topic: str = "", days: int = 7, limit: int = 20) -> dict:
    with timer() as t:
        if not topic:
            return result(
                name       = NAME,
                status     = "FAILED",
                mode       = "no topic",
                duration_s = t.elapsed,
                insights   = [],
                error      = "topic parameter is required",
            )

        try:
            rss_url = GNEWS_RSS.format(q=urllib.parse.quote(topic))
            _log(f"Fetching Google News RSS → {rss_url[:80]}...")
            articles = _fetch_google_news(topic, limit=limit)
            _log(f"  ← {len(articles)} articles")

            _log("Checking NewsAPI enrichment...")
            extra    = _fetch_newsapi(topic, days=days, limit=limit)
            if extra:
                _log(f"  ← {len(extra)} additional articles from NewsAPI")
            else:
                _log("  ← NewsAPI skipped (no key or no results)")

            # Dedupe by url
            seen = {a["url"] for a in articles}
            for a in extra:
                if a["url"] not in seen:
                    articles.append(a)
                    seen.add(a["url"])

            # Fetch full article bodies for top articles
            from agentshub.tools.web_fetch import fetch_articles_parallel

            fetchable = [a for a in articles if "news.google.com/rss/articles" not in a["url"]][:5]
            if fetchable:
                _log(f"Fetching {len(fetchable)} article bodies in parallel...")
                fetch_results = fetch_articles_parallel([a["url"] for a in fetchable])
                fetched_count = 0
                for article, fetched in zip(fetchable, fetch_results):
                    if fetched["status"] == "ok" and fetched["text"]:
                        article["full_text"] = fetched["text"][:4000]
                        fetched_count += 1
                        _log(f"  ← {fetched['chars']} chars from {fetched['source']}")
                    elif fetched["status"] in ("blocked", "redirect"):
                        _log(f"  ✗ {fetched['source']}: {fetched.get('reason', 'skipped')}")
                _log(f"  {fetched_count}/{len(fetchable)} articles fetched successfully")
            else:
                _log("  No directly fetchable URLs (all Google News redirects)")

            # Recurring themes
            themes = _theme_keywords(articles)

            # Source diversity
            sources = Counter(a["source"] for a in articles if a["source"])

            mode = f"LIVE — Google News RSS + article fetch"
            if extra:
                mode += " + NewsAPI"

            return result(
                name       = NAME,
                status     = "SUCCESS",
                mode       = mode,
                duration_s = t.elapsed,
                insights   = [
                    {
                        "type":    "article volume",
                        "finding": f"{len(articles)} articles for '{topic}' from {len(sources)} sources",
                    },
                    {
                        "type":    "article detail",
                        "finding": f"{fetched_count if fetchable else 0} full article bodies fetched for deeper analysis",
                    },
                    {
                        "type":    "recurring themes",
                        "finding": "Most common keywords across headlines",
                        "themes":  [{"word": w, "count": c} for w, c in themes],
                    },
                ],
                articles   = articles[:limit],
                topic      = topic,
            )

        except Exception as exc:
            return result(
                name       = NAME,
                status     = "FAILED",
                mode       = "fetch error",
                duration_s = t.elapsed,
                insights   = [],
                error      = str(exc),
            )
