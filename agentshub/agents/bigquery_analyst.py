"""
BigQuery Analyst Agent — runs SQL queries against any BigQuery public dataset.

Takes a SQL query (written by the supervisor/orchestrator) and executes it.
The supervisor handles query generation — this agent handles execution,
result formatting, and error reporting.

Can also list available public datasets and table schemas to help the
supervisor write correct SQL.

Data source: Any BigQuery public dataset (bigquery-public-data.*).
"""

import os
import json
from datetime import datetime
from google.cloud import bigquery
from agentshub.base import result, timer

NAME = "bigquery_analyst"
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [bigquery_analyst] {msg}", flush=True)


def run(query: str = "", dataset: str = "", action: str = "query", limit: int = 20) -> dict:
    """
    Execute SQL against BigQuery public datasets, or inspect schemas.

    Args:
        query: SQL query to execute (for action="query")
        dataset: Dataset to inspect (for action="schema", e.g. "bigquery-public-data.google_trends")
        action: "query" to run SQL, "schema" to list tables/columns in a dataset
        limit: Max rows to return (default 20, applied if query doesn't have LIMIT)
    """
    with timer() as t:
        if not PROJECT:
            return result(
                name=NAME, status="FAILED", mode="no GCP project",
                duration_s=t.elapsed, insights=[],
                error="Set GOOGLE_CLOUD_PROJECT in .env",
            )

        try:
            client = bigquery.Client(project=PROJECT)

            if action == "schema":
                return _run_schema(client, dataset, t)
            else:
                return _run_query(client, query, limit, t)

        except Exception as exc:
            _log(f"  ✗ BigQuery error: {exc}")
            return result(
                name=NAME, status="FAILED", mode="BQ error",
                duration_s=t.elapsed, insights=[],
                error=str(exc),
            )


def _run_schema(client, dataset: str, t) -> dict:
    """List tables and their columns for a dataset."""
    if not dataset:
        return result(
            name=NAME, status="FAILED", mode="no dataset",
            duration_s=t.elapsed, insights=[],
            error="dataset parameter required for action='schema'",
        )

    _log(f"Listing tables in {dataset}")

    tables_info = []
    try:
        tables = list(client.list_tables(dataset))
        for table_ref in tables[:20]:
            table = client.get_table(table_ref)
            columns = [
                {"name": f.name, "type": f.field_type, "description": f.description or ""}
                for f in table.schema[:15]
            ]
            tables_info.append({
                "table": f"{dataset}.{table.table_id}",
                "rows": table.num_rows,
                "columns": columns,
            })
            _log(f"  {table.table_id}: {table.num_rows:,} rows, {len(table.schema)} columns")
    except Exception as exc:
        return result(
            name=NAME, status="FAILED", mode="schema error",
            duration_s=t.elapsed, insights=[],
            error=f"Could not list tables in {dataset}: {exc}",
        )

    return result(
        name=NAME,
        status="SUCCESS",
        mode=f"SCHEMA — {dataset} ({len(tables_info)} tables)",
        duration_s=t.elapsed,
        insights=[{"type": "schema", "finding": f"{len(tables_info)} tables in {dataset}"}],
        tables=tables_info,
        dataset=dataset,
    )


def _run_query(client, query: str, limit: int, t) -> dict:
    """Execute a SQL query and return results."""
    if not query:
        return result(
            name=NAME, status="FAILED", mode="no query",
            duration_s=t.elapsed, insights=[],
            error="query parameter required for action='query'",
        )

    # Safety: only allow SELECT queries
    stripped = query.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        return result(
            name=NAME, status="FAILED", mode="blocked",
            duration_s=t.elapsed, insights=[],
            error="Only SELECT/WITH queries allowed. No INSERT/UPDATE/DELETE/DROP.",
        )

    # Add LIMIT if not present
    if "LIMIT" not in query.upper():
        query = f"{query}\nLIMIT {limit}"

    _log(f"Executing SQL query...")
    _log(f"  {query[:120]}...")

    rows = list(client.query(query).result())
    _log(f"  ← {len(rows)} rows returned")

    # Convert to list of dicts
    if rows:
        columns = [field.name for field in rows[0]._xxx_field_to_index.keys()] if hasattr(rows[0], '_xxx_field_to_index') else []
        data = [dict(row) for row in rows]
        # Convert non-serializable types
        for row in data:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
                elif not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    row[k] = str(v)
    else:
        data = []

    return result(
        name=NAME,
        status="SUCCESS",
        mode=f"LIVE — query returned {len(data)} rows",
        duration_s=t.elapsed,
        insights=[{"type": "query result", "finding": f"{len(data)} rows returned"}],
        data=data,
        query=query,
        row_count=len(data),
    )
