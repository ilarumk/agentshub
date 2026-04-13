"""
Generic fan-out / fan-in orchestrator.

Runs N agents in parallel using a thread pool, returns merged results.
Used by the scheduler and CLI; the MCP server bypasses this and lets the
LLM client (Claude Desktop) decide which agents to call.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from agentshub.agents import REGISTRY, get_run


def run_parallel(
    plan: list[tuple[str, dict[str, Any]]],
    on_result: Callable[[str, dict, float], None] | None = None,
) -> dict[str, dict]:
    """
    Run multiple agents simultaneously.

    plan: list of (agent_name, params) tuples
    on_result: optional callback fired as each agent completes
    Returns: dict mapping agent name → result
    """
    results: dict[str, dict] = {}
    start = time.time()

    with ThreadPoolExecutor(max_workers=max(1, len(plan))) as pool:
        future_map = {
            pool.submit(get_run(name), **params): name
            for name, params in plan
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                res = future.result()
            except Exception as exc:
                res = {
                    "agent":      name,
                    "status":     "FAILED",
                    "mode":       "uncaught exception",
                    "duration_s": 0,
                    "insights":   [],
                    "error":      str(exc),
                }
            wall = time.time() - start
            results[name] = res
            if on_result:
                on_result(name, res, wall)

    return results


def run_sequential(
    plan: list[tuple[str, dict[str, Any]]],
    on_result: Callable[[str, dict, float], None] | None = None,
) -> dict[str, dict]:
    """Sequential execution — useful for debugging or sequential-vs-parallel comparisons."""
    results: dict[str, dict] = {}
    start = time.time()

    for name, params in plan:
        try:
            res = get_run(name)(**params)
        except Exception as exc:
            res = {
                "agent":      name,
                "status":     "FAILED",
                "mode":       "uncaught exception",
                "duration_s": 0,
                "insights":   [],
                "error":      str(exc),
            }
        wall = time.time() - start
        results[name] = res
        if on_result:
            on_result(name, res, wall)

    return results


def list_available_agents() -> list[dict]:
    return [{"name": m["name"], "description": m["description"]} for m in REGISTRY]
