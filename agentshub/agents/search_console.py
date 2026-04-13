"""
Search Console Agent — Google Search Console SEO insights.

Pulls organic search performance: top queries, impressions, CTR, position.
Identifies quick-win opportunities (high impressions, low CTR).

Requires: GSC_SITE_URL env var + Google ADC with Search Console access.
Falls back to mock data if credentials unavailable.
"""

import os
from datetime import datetime, timedelta
from agentshub.base import result, timer

NAME = "search_console"


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [search_console] {msg}", flush=True)


def _run_live(site_url: str, days: int = 30) -> dict:
    from googleapiclient.discovery import build
    import google.auth

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    _log(f"Querying GSC API → {site_url} ({start_date} to {end_date})")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "rowLimit": 20,
        "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
    }
    resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = resp.get("rows", [])
    _log(f"  ← {len(rows)} queries returned")

    terms = [
        {
            "query": r["keys"][0],
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr_pct": round(r.get("ctr", 0) * 100, 1),
            "position": round(r.get("position", 0), 1),
        }
        for r in rows
    ]

    # Quick wins: high impressions but low CTR
    quick_wins = [t for t in terms if t["impressions"] > 200 and t["ctr_pct"] < 5.0]

    return {
        "terms": terms,
        "quick_wins": quick_wins,
        "site_url": site_url,
        "date_range": f"{start_date} to {end_date}",
    }


def run(site_url: str = "", days: int = 30) -> dict:
    """
    Pull Google Search Console data for a site.

    Args:
        site_url: The site URL (e.g. "https://example.com"). Uses GSC_SITE_URL env var if empty.
        days: Lookback window in days (default 30).
    """
    with timer() as t:
        url = site_url or os.getenv("GSC_SITE_URL", "")

        if not url:
            return result(
                name=NAME, status="FAILED", mode="no site URL",
                duration_s=t.elapsed, insights=[],
                error="Provide site_url parameter or set GSC_SITE_URL env var",
            )

        try:
            _log(f"Connecting to Google Search Console for {url}")
            data = _run_live(url, days)

            insights = [
                {
                    "type": "top queries",
                    "finding": f"{len(data['terms'])} queries, top: {', '.join(t['query'] for t in data['terms'][:5])}",
                },
                {
                    "type": "quick-win opportunities",
                    "finding": f"{len(data['quick_wins'])} queries with >200 impressions but <5% CTR",
                    "queries": [t["query"] for t in data["quick_wins"][:5]],
                },
            ]

            return result(
                name=NAME,
                status="SUCCESS",
                mode=f"LIVE — {url} ({data['date_range']})",
                duration_s=t.elapsed,
                insights=insights,
                terms=data["terms"],
                quick_wins=data["quick_wins"],
                site_url=url,
            )

        except Exception as exc:
            _log(f"  ✗ GSC API failed: {exc}")
            return result(
                name=NAME, status="FAILED", mode="GSC API error",
                duration_s=t.elapsed, insights=[],
                error=str(exc),
            )
