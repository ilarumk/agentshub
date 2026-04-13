"""
BBC News Agent — searches BBC News articles via BigQuery public dataset.

Queries bigquery-public-data.bbc_news.fulltext for articles matching
keywords. Returns article titles, descriptions, and body text.

Data source: BigQuery public dataset (free to query).
"""

import os
import json
from datetime import datetime
from google.cloud import bigquery
from agentshub.base import result, timer

NAME = "bbc_news"
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

SEARCH_QUERY = """
SELECT
  title,
  description,
  SUBSTR(body, 0, 500) AS body_preview,
  filename
FROM `bigquery-public-data.bbc_news.fulltext`
WHERE LOWER(body) LIKE LOWER(@keyword1)
   OR LOWER(body) LIKE LOWER(@keyword2)
   OR LOWER(body) LIKE LOWER(@keyword3)
   OR LOWER(title) LIKE LOWER(@keyword1)
   OR LOWER(title) LIKE LOWER(@keyword2)
   OR LOWER(title) LIKE LOWER(@keyword3)
LIMIT @limit_val
"""


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [bbc_news] {msg}", flush=True)


def run(topic: str = "", limit: int = 10) -> dict:
    """
    Search BBC News articles by topic.

    Args:
        topic: Topic or keywords to search (e.g. "artificial intelligence", "climate change")
        limit: Max articles to return (default 10)
    """
    with timer() as t:
        if not topic:
            return result(
                name=NAME, status="FAILED", mode="no topic",
                duration_s=t.elapsed, insights=[],
                error="topic parameter is required",
            )

        if not PROJECT:
            return result(
                name=NAME, status="FAILED", mode="no GCP project",
                duration_s=t.elapsed, insights=[],
                error="Set GOOGLE_CLOUD_PROJECT in .env",
            )

        try:
            # Generate search variations from the topic
            words = topic.strip().split()
            keyword1 = f"%{topic}%"
            keyword2 = f"%{words[0]}%" if words else keyword1
            keyword3 = f"%{' '.join(words[:2])}%" if len(words) >= 2 else keyword1

            _log(f"Querying BigQuery → bigquery-public-data.bbc_news.fulltext")
            _log(f"  Keywords: '{keyword1}', '{keyword2}', '{keyword3}'")

            client = bigquery.Client(project=PROJECT)

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("keyword1", "STRING", keyword1),
                    bigquery.ScalarQueryParameter("keyword2", "STRING", keyword2),
                    bigquery.ScalarQueryParameter("keyword3", "STRING", keyword3),
                    bigquery.ScalarQueryParameter("limit_val", "INT64", limit),
                ]
            )

            rows = list(client.query(SEARCH_QUERY, job_config=job_config).result())
            _log(f"  ← {len(rows)} articles returned")

            articles = [
                {
                    "title": r["title"],
                    "description": r["description"],
                    "body_preview": r["body_preview"],
                    "category": r["filename"].split("/")[0] if r["filename"] else "",
                }
                for r in rows
            ]

            # Count categories
            categories = {}
            for a in articles:
                cat = a["category"]
                categories[cat] = categories.get(cat, 0) + 1

            insights = [
                {
                    "type": "article volume",
                    "finding": f"{len(articles)} BBC articles matching '{topic}'",
                },
                {
                    "type": "categories",
                    "finding": f"Categories: {json.dumps(categories)}",
                },
            ]

            return result(
                name=NAME,
                status="SUCCESS",
                mode=f"LIVE — BigQuery bbc_news.fulltext",
                duration_s=t.elapsed,
                insights=insights,
                articles=articles,
                topic=topic,
            )

        except Exception as exc:
            _log(f"  ✗ BigQuery error: {exc}")
            return result(
                name=NAME, status="FAILED", mode="BQ error",
                duration_s=t.elapsed, insights=[],
                error=str(exc),
            )
