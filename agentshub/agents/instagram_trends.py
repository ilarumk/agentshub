"""
Instagram Trends Agent — discovers trending content via Apify.

Searches Instagram hashtags for viral posts, extracts creator profiles,
aggregates trends (hashtags, hooks, content types, engagement patterns).

Requires: APIFY_TOKEN in .env

Three-step pipeline:
  1. Search hashtags for recent posts via Apify
  2. Check discovered accounts for viral content
  3. Aggregate trends across all viral posts
"""

import os
import re
import json
import httpx
import asyncio
from collections import Counter
from datetime import datetime
from agentshub.base import result, timer

NAME = "instagram_trends"
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
ACTOR_INSTAGRAM = "apify~instagram-scraper"
BASE_URL = "https://api.apify.com/v2"

VIRAL_VIEWS_THRESHOLD = 100_000
VIRAL_LIKES_THRESHOLD = 10_000


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [instagram_trends] {msg}", flush=True)


async def _search_hashtags(hashtags: list[str], posts_per_hashtag: int = 30) -> list[dict]:
    """Search hashtags for recent posts, return unique accounts."""
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}
    all_posts = []

    async with httpx.AsyncClient(timeout=300) as client:
        for hashtag in hashtags:
            _log(f"Searching #{hashtag}...")
            try:
                r = await client.post(
                    f"{BASE_URL}/acts/{ACTOR_INSTAGRAM}/run-sync-get-dataset-items",
                    headers=headers,
                    params={"token": APIFY_TOKEN},
                    json={
                        "directUrls": [f"https://www.instagram.com/explore/tags/{hashtag}/"],
                        "resultsType": "posts",
                        "resultsLimit": posts_per_hashtag,
                    },
                )
                if r.status_code in [200, 201]:
                    data = r.json()
                    posts = data if isinstance(data, list) else data.get("items", [])
                    accounts = set(p.get("ownerUsername", "") for p in posts if p.get("ownerUsername"))
                    _log(f"  ← #{hashtag}: {len(posts)} posts from {len(accounts)} accounts")
                    for p in posts:
                        owner = p.get("ownerUsername", "")
                        if owner:
                            all_posts.append({"owner": owner, "hashtag": hashtag})
            except Exception as e:
                _log(f"  ✗ #{hashtag}: {str(e)[:50]}")
    return all_posts


async def _check_accounts_for_viral(accounts: list[str], limit: int = 20) -> list[dict]:
    """Check accounts for viral content, return those with viral posts."""
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}
    accounts_to_check = accounts[:limit]
    viral_accounts = []

    _log(f"Checking {len(accounts_to_check)} accounts for viral content...")

    for handle in accounts_to_check:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{BASE_URL}/acts/{ACTOR_INSTAGRAM}/run-sync-get-dataset-items",
                    headers=headers,
                    params={"token": APIFY_TOKEN},
                    json={
                        "directUrls": [f"https://www.instagram.com/{handle}/"],
                        "resultsType": "posts",
                        "resultsLimit": 10,
                    },
                )
                if r.status_code in [200, 201]:
                    posts = r.json()
                    viral_posts = []
                    for post in posts:
                        views = post.get("videoViewCount", 0) or post.get("videoPlayCount", 0)
                        likes = post.get("likesCount", 0)
                        if views >= VIRAL_VIEWS_THRESHOLD or likes >= VIRAL_LIKES_THRESHOLD:
                            viral_posts.append({
                                "handle": handle,
                                "caption": (post.get("caption") or "")[:200],
                                "views": views,
                                "likes": likes,
                                "comments": post.get("commentsCount", 0),
                                "type": post.get("type", "unknown"),
                                "hashtags": re.findall(r"#\w+", post.get("caption") or ""),
                                "url": post.get("url", ""),
                                "timestamp": post.get("timestamp", ""),
                            })
                    if viral_posts:
                        _log(f"  ✓ @{handle}: {len(viral_posts)} viral posts")
                        viral_accounts.append({
                            "handle": handle,
                            "viral_count": len(viral_posts),
                            "total_engagement": sum(p["views"] + p["likes"] for p in viral_posts),
                            "posts": viral_posts,
                        })
        except Exception:
            continue

    viral_accounts.sort(key=lambda x: x["total_engagement"], reverse=True)
    return viral_accounts


def _aggregate(viral_accounts: list[dict]) -> dict:
    """Aggregate trends across all viral posts."""
    all_posts = [p for acc in viral_accounts for p in acc["posts"]]

    hashtag_freq = Counter(h for p in all_posts for h in p["hashtags"])
    content_types = Counter(p["type"] for p in all_posts)

    hooks = [p["caption"][:50].strip() for p in all_posts if p["caption"]]

    captions = " ".join(p["caption"] for p in all_posts)
    words = re.findall(r'\b[a-z]{4,}\b', re.sub(r"#\w+|http\S+", "", captions).lower())
    stop = {"that", "this", "with", "from", "have", "your", "like", "just", "what", "when", "more"}
    keywords = Counter(w for w in words if w not in stop).most_common(15)

    return {
        "total_viral_posts": len(all_posts),
        "top_hashtags": dict(hashtag_freq.most_common(20)),
        "content_types": dict(content_types),
        "viral_hooks": hooks[:15],
        "common_keywords": dict(keywords),
        "top_posts": sorted(all_posts, key=lambda x: x["views"] + x["likes"], reverse=True)[:10],
        "accounts": [{"handle": a["handle"], "viral_count": a["viral_count"], "engagement": a["total_engagement"]} for a in viral_accounts],
    }


def run(
    topic: str = "skincare",
    hashtags: str = "",
    max_accounts: int = 20,
) -> dict:
    """
    Discover Instagram trends for a topic.

    Args:
        topic: Topic to search (e.g. "skincare", "fitness", "cooking")
        hashtags: Comma-separated hashtags to search. If empty, generates from topic.
        max_accounts: Max accounts to check for viral content (default 20)
    """
    with timer() as t:
        if not APIFY_TOKEN:
            return result(
                name=NAME, status="FAILED", mode="no API key",
                duration_s=t.elapsed, insights=[],
                error="APIFY_TOKEN not set in .env",
            )

        # Generate hashtags from topic if not provided
        if hashtags:
            tag_list = [h.strip().lstrip("#") for h in hashtags.split(",")]
        else:
            tag_list = [topic, f"{topic}tips", f"{topic}routine", f"{topic}community",
                        f"trending{topic}", f"{topic}hack"]

        _log(f"Searching {len(tag_list)} hashtags for '{topic}'")

        # Step 1: Search hashtags
        posts = asyncio.run(_search_hashtags(tag_list))
        unique_accounts = list(set(p["owner"] for p in posts))
        _log(f"Found {len(unique_accounts)} unique accounts")

        if not unique_accounts:
            return result(
                name=NAME, status="PARTIAL", mode=f"no accounts found for '{topic}'",
                duration_s=t.elapsed, insights=[{"type": "coverage", "finding": "No accounts found"}],
            )

        # Step 2: Check for viral content
        viral_accounts = asyncio.run(_check_accounts_for_viral(unique_accounts, max_accounts))
        _log(f"{len(viral_accounts)} accounts with viral content")

        if not viral_accounts:
            return result(
                name=NAME, status="PARTIAL",
                mode=f"LIVE — {len(unique_accounts)} accounts checked, no viral content found",
                duration_s=t.elapsed,
                insights=[{"type": "coverage", "finding": f"Checked {len(unique_accounts)} accounts, none had viral posts"}],
            )

        # Step 3: Aggregate trends
        trends = _aggregate(viral_accounts)
        _log(f"Aggregated {trends['total_viral_posts']} viral posts from {len(viral_accounts)} accounts")

        insights = [
            {"type": "viral content", "finding": f"{trends['total_viral_posts']} viral posts across {len(viral_accounts)} accounts"},
            {"type": "top hashtags", "finding": f"Top: {', '.join(list(trends['top_hashtags'].keys())[:5])}"},
            {"type": "content types", "finding": json.dumps(trends["content_types"])},
            {"type": "viral hooks", "finding": f"{len(trends['viral_hooks'])} hook patterns identified"},
        ]

        return result(
            name=NAME,
            status="SUCCESS",
            mode=f"LIVE — Apify Instagram scraper, {len(tag_list)} hashtags, {len(viral_accounts)} accounts",
            duration_s=t.elapsed,
            insights=insights,
            trends=trends,
            topic=topic,
        )
