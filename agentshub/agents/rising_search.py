"""
Rising Search Agent — BigQuery Google Trends.

Returns the top rising and popular search terms nationally.
NO keyword filtering — the dataset is small (~25 terms) so we return
everything and let the LLM caller interpret relevance to the user's topic.

This is intentional: the LLM can spot "gonzo cheese" as food-related,
but SQL LIKE matching never would unless someone pre-guessed "cheese."

Live data: bigquery-public-data.google_trends (updated daily).
"""

import os
from google.cloud import bigquery
from agentshub.base import result, timer

NAME    = "rising_search"
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

RISING_QUERY = """
WITH latest AS (
  SELECT MAX(refresh_date) AS rd FROM `bigquery-public-data.google_trends.top_rising_terms`
),
latest_week AS (
  SELECT MAX(week) AS wk FROM `bigquery-public-data.google_trends.top_rising_terms`
  WHERE refresh_date = (SELECT rd FROM latest)
)
SELECT
  term,
  SUM(percent_gain)         AS total_gain,
  COUNT(DISTINCT dma_name)  AS dma_count,
  (SELECT rd FROM latest)   AS refresh_date,
  (SELECT wk FROM latest_week) AS week
FROM `bigquery-public-data.google_trends.top_rising_terms`
WHERE refresh_date = (SELECT rd FROM latest)
  AND week         = (SELECT wk FROM latest_week)
GROUP BY term
ORDER BY total_gain DESC
LIMIT 30
"""

TOP_QUERY = """
WITH latest AS (
  SELECT MAX(refresh_date) AS rd FROM `bigquery-public-data.google_trends.top_terms`
),
latest_week AS (
  SELECT MAX(week) AS wk FROM `bigquery-public-data.google_trends.top_terms`
  WHERE refresh_date = (SELECT rd FROM latest)
)
SELECT
  term,
  SUM(score)                AS total_score,
  COUNT(DISTINCT dma_name)  AS dma_count,
  (SELECT rd FROM latest)   AS refresh_date,
  (SELECT wk FROM latest_week) AS week
FROM `bigquery-public-data.google_trends.top_terms`
WHERE refresh_date = (SELECT rd FROM latest)
  AND week         = (SELECT wk FROM latest_week)
GROUP BY term
ORDER BY total_score DESC
LIMIT 25
"""


def _log(msg):
    from datetime import datetime
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [rising_search] {msg}", flush=True)


def run() -> dict:
    """Returns ALL top rising + popular search terms nationally.
    No filtering — the LLM caller decides which are relevant to the user's topic."""
    with timer() as t:
        try:
            _log(f"Connecting to BigQuery (project: {PROJECT})")
            client = bigquery.Client(project=PROJECT)

            _log("Running SQL → bigquery-public-data.google_trends.top_rising_terms")
            _log("  SELECT term, SUM(percent_gain), COUNT(DISTINCT dma_name) ... LIMIT 30")
            rising_rows = list(client.query(RISING_QUERY).result())
            rising = [
                {"term": r["term"], "gain_pct": r["total_gain"], "dma_count": r["dma_count"]}
                for r in rising_rows
            ]
            _log(f"  ← {len(rising)} rising terms returned")

            _log("Running SQL → bigquery-public-data.google_trends.top_terms")
            _log("  SELECT term, SUM(score), COUNT(DISTINCT dma_name) ... LIMIT 25")
            top_rows = list(client.query(TOP_QUERY).result())
            top = [
                {"term": r["term"], "total_score": r["total_score"], "dma_count": r["dma_count"]}
                for r in top_rows
            ]
            _log(f"  ← {len(top)} popular terms returned")

            refresh = (rising_rows or top_rows)[0]["refresh_date"] if (rising_rows or top_rows) else "?"
            week    = (rising_rows or top_rows)[0]["week"] if (rising_rows or top_rows) else "?"

            return result(
                name       = NAME,
                status     = "SUCCESS",
                mode       = f"LIVE — refresh={refresh}, week={week}",
                duration_s = t.elapsed,
                insights   = [
                    {
                        "type":    "fastest rising nationally",
                        "finding": f"{len(rising)} rising terms, top: {', '.join(r['term'] for r in rising[:5])}",
                    },
                    {
                        "type":    "highest volume nationally",
                        "finding": f"{len(top)} popular terms, top: {', '.join(r['term'] for r in top[:5])}",
                    },
                ],
                rising     = rising,
                top        = top,
            )

        except Exception as exc:
            return result(
                name       = NAME,
                status     = "FAILED",
                mode       = "BQ error",
                duration_s = t.elapsed,
                insights   = [],
                error      = str(exc),
            )
