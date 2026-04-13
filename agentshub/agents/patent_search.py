"""
Patent Search Agent — searches Google Patents via BigQuery public dataset.

Queries patents-public-data.patents.publications for patents matching
keywords in title and abstract. Returns filing trends, top assignees,
and recent filings.

The supervisor/orchestrator handles query expansion — it can call this
agent multiple times with different keywords to broaden the search
(e.g. "AI chips" → also search "neural processing unit", "machine learning
accelerator", "inference hardware"). This agent does exact keyword matching.

Data source: BigQuery public dataset — 90M+ patent publications from 17 countries.
"""

import os
import json
from datetime import datetime
from google.cloud import bigquery
from agentshub.base import result, timer

NAME = "patent_search"
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# Search patents by keyword in title and abstract
SEARCH_QUERY = """
SELECT
  publication_number,
  ARRAY_TO_STRING(
    ARRAY(SELECT a.name FROM UNNEST(assignee_harmonized) a LIMIT 3), ', '
  ) AS assignees,
  title_localized[SAFE_OFFSET(0)].text AS title,
  SUBSTR(abstract_localized[SAFE_OFFSET(0)].text, 0, 300) AS abstract_preview,
  filing_date,
  grant_date,
  country_code,
  ARRAY_LENGTH(claims_localized) AS num_claims
FROM `patents-public-data.patents.publications`
WHERE
  (LOWER(title_localized[SAFE_OFFSET(0)].text) LIKE LOWER(@keyword)
   OR LOWER(abstract_localized[SAFE_OFFSET(0)].text) LIKE LOWER(@keyword))
  AND filing_date >= @since_date
ORDER BY filing_date DESC
LIMIT @limit_val
"""

# Count filings over time by assignee
VELOCITY_QUERY = """
SELECT
  EXTRACT(YEAR FROM filing_date) AS filing_year,
  ARRAY_TO_STRING(
    ARRAY(SELECT a.name FROM UNNEST(assignee_harmonized) a LIMIT 1), ', '
  ) AS top_assignee,
  COUNT(*) AS filing_count
FROM `patents-public-data.patents.publications`
WHERE
  (LOWER(title_localized[SAFE_OFFSET(0)].text) LIKE LOWER(@keyword)
   OR LOWER(abstract_localized[SAFE_OFFSET(0)].text) LIKE LOWER(@keyword))
  AND filing_date >= @since_date
GROUP BY filing_year, top_assignee
ORDER BY filing_count DESC
LIMIT 20
"""


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [patent_search] {msg}", flush=True)


def run(keywords: str = "", years_back: int = 5, limit: int = 15) -> dict:
    """
    Search patents by keyword. The supervisor can call this multiple times
    with different keywords to expand the search.

    Args:
        keywords: Search terms (e.g. "AI chips", "quantum computing"). Searches title and abstract.
        years_back: How many years of filings to include (default 5)
        limit: Max patents to return (default 15)
    """
    with timer() as t:
        if not keywords:
            return result(
                name=NAME, status="FAILED", mode="no keywords",
                duration_s=t.elapsed, insights=[],
                error="keywords parameter is required",
            )

        if not PROJECT:
            return result(
                name=NAME, status="FAILED", mode="no GCP project",
                duration_s=t.elapsed, insights=[],
                error="Set GOOGLE_CLOUD_PROJECT in .env",
            )

        try:
            keyword_param = f"%{keywords}%"
            since = f"{datetime.now().year - years_back}-01-01"

            _log(f"Querying BigQuery → patents-public-data.patents.publications")
            _log(f"  Keywords: '{keywords}' | Since: {since}")

            client = bigquery.Client(project=PROJECT)

            # Run patent search
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("keyword", "STRING", keyword_param),
                    bigquery.ScalarQueryParameter("since_date", "STRING", since),
                    bigquery.ScalarQueryParameter("limit_val", "INT64", limit),
                ]
            )

            _log(f"  Running patent search...")
            rows = list(client.query(SEARCH_QUERY, job_config=job_config).result())
            _log(f"  ← {len(rows)} patents returned")

            patents = [
                {
                    "publication_number": r["publication_number"],
                    "title": r["title"] or "",
                    "abstract_preview": r["abstract_preview"] or "",
                    "assignees": r["assignees"] or "",
                    "filing_date": str(r["filing_date"]) if r["filing_date"] else "",
                    "country": r["country_code"] or "",
                    "claims": r["num_claims"] or 0,
                }
                for r in rows
            ]

            # Run velocity query
            _log(f"  Running filing velocity query...")
            velocity_rows = list(client.query(VELOCITY_QUERY, job_config=job_config).result())
            _log(f"  ← {len(velocity_rows)} assignee-year combinations")

            velocity = [
                {
                    "year": r["filing_year"],
                    "assignee": r["top_assignee"] or "Unknown",
                    "filings": r["filing_count"],
                }
                for r in velocity_rows
            ]

            # Top assignees
            assignee_totals = {}
            for v in velocity:
                a = v["assignee"]
                assignee_totals[a] = assignee_totals.get(a, 0) + v["filings"]
            top_assignees = sorted(assignee_totals.items(), key=lambda x: x[1], reverse=True)[:10]

            # Countries
            countries = {}
            for p in patents:
                c = p["country"]
                countries[c] = countries.get(c, 0) + 1

            insights = [
                {
                    "type": "patent volume",
                    "finding": f"{len(patents)} patents matching '{keywords}' since {since}",
                },
                {
                    "type": "top assignees",
                    "finding": f"Top filers: {', '.join(f'{a}({c})' for a, c in top_assignees[:5])}",
                },
                {
                    "type": "filing velocity",
                    "finding": f"{len(velocity)} assignee-year data points",
                    "data": velocity[:10],
                },
                {
                    "type": "countries",
                    "finding": f"Countries: {json.dumps(countries)}",
                },
            ]

            return result(
                name=NAME,
                status="SUCCESS",
                mode=f"LIVE — BigQuery patents-public-data ({years_back}yr lookback)",
                duration_s=t.elapsed,
                insights=insights,
                patents=patents,
                velocity=velocity,
                top_assignees=dict(top_assignees),
                keywords=keywords,
            )

        except Exception as exc:
            _log(f"  ✗ BigQuery error: {exc}")
            return result(
                name=NAME, status="FAILED", mode="BQ error",
                duration_s=t.elapsed, insights=[],
                error=str(exc),
            )
