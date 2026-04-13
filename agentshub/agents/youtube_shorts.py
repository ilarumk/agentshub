"""
YouTube Shorts / Trending Agent — YouTube Data API v3.

Two strategies:
  1. chart=mostPopular by region/category (1 quota unit) — uses default trending list
  2. search.list with topic keyword (100 quota units) — used when topic is provided

Set YOUTUBE_API_KEY in env to use real data.
"""

import os
import json
import urllib.request
import urllib.parse
from agentshub.base import result, timer

NAME    = "youtube_shorts"
API_KEY = os.getenv("YOUTUBE_API_KEY", "")
HEADERS = {"User-Agent": "agentshub/0.1"}

YT_BASE = "https://www.googleapis.com/youtube/v3"


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read())


def _parse_duration(iso: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to seconds."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + s


def _trending_by_region(region: str, max_results: int) -> list[dict]:
    params = {
        "part":       "snippet,statistics,contentDetails",
        "chart":      "mostPopular",
        "regionCode": region,
        "maxResults": str(max_results),
        "key":        API_KEY,
    }
    url  = f"{YT_BASE}/videos?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    return data.get("items", [])


def _search_topic(topic: str, max_results: int) -> list[dict]:
    # Step 1: search for videos
    sparams = {
        "part":          "snippet",
        "q":             topic,
        "type":          "video",
        "order":         "viewCount",
        "publishedAfter": _days_ago_iso(7),
        "maxResults":    str(max_results),
        "key":           API_KEY,
    }
    url  = f"{YT_BASE}/search?{urllib.parse.urlencode(sparams)}"
    data = _http_get(url)
    ids  = [item["id"]["videoId"] for item in data.get("items", []) if "videoId" in item.get("id", {})]
    if not ids:
        return []

    # Step 2: hydrate with statistics + contentDetails
    vparams = {
        "part": "snippet,statistics,contentDetails",
        "id":   ",".join(ids),
        "key":  API_KEY,
    }
    url2 = f"{YT_BASE}/videos?{urllib.parse.urlencode(vparams)}"
    return _http_get(url2).get("items", [])


def _days_ago_iso(days: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.utcnow() - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shape(item: dict) -> dict:
    sn = item.get("snippet", {})
    st = item.get("statistics", {})
    cd = item.get("contentDetails", {})
    duration = _parse_duration(cd.get("duration", ""))
    return {
        "title":      sn.get("title", ""),
        "channel":    sn.get("channelTitle", ""),
        "published":  sn.get("publishedAt", ""),
        "views":      int(st.get("viewCount", 0)),
        "likes":      int(st.get("likeCount", 0)),
        "comments":   int(st.get("commentCount", 0)),
        "duration_s": duration,
        "is_short":   duration > 0 and duration <= 60,
        "url":        f"https://www.youtube.com/watch?v={item.get('id') if isinstance(item.get('id'), str) else item.get('id', {}).get('videoId', '')}",
    }


def run(topic: str = "", region: str = "US", shorts_only: bool = False) -> dict:
    with timer() as t:
        if not API_KEY:
            return result(
                name       = NAME,
                status     = "FAILED",
                mode       = "missing YOUTUBE_API_KEY",
                duration_s = t.elapsed,
                insights   = [],
                error      = "Set YOUTUBE_API_KEY in env. Free key from Google Cloud Console.",
            )

        try:
            raw = _search_topic(topic, max_results=25) if topic \
                  else _trending_by_region(region, max_results=25)

            videos = [_shape(v) for v in raw]
            if shorts_only:
                videos = [v for v in videos if v["is_short"]]

            videos.sort(key=lambda v: v["views"], reverse=True)
            top = videos[:15]

            insights = [
                {
                    "type":    "trending volume",
                    "finding": f"{len(top)} videos returned for '{topic or region}'"
                               f"{' (shorts only)' if shorts_only else ''}",
                },
            ]
            if top:
                top_video = top[0]
                insights.append({
                    "type":    "top video",
                    "finding": f"'{top_video['title'][:60]}' by {top_video['channel']} "
                               f"— {top_video['views']:,} views",
                })

            return result(
                name       = NAME,
                status     = "SUCCESS",
                mode       = f"LIVE — YouTube Data API v3 (topic={topic or 'trending'}, region={region})",
                duration_s = t.elapsed,
                insights   = insights,
                videos     = top,
            )

        except Exception as exc:
            return result(
                name       = NAME,
                status     = "FAILED",
                mode       = "API error",
                duration_s = t.elapsed,
                insights   = [],
                error      = str(exc),
            )
