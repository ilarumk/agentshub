"""
Base contract for agents.

Every agent exposes a `run(**kwargs) -> AgentResult` function.
Results follow a standardized dict shape so the orchestrator and
synthesizer can treat every agent the same way.
"""

import time
from contextlib import contextmanager
from typing import Any, TypedDict, NotRequired


class AgentResult(TypedDict):
    agent:      str
    status:     str   # SUCCESS | PARTIAL | MOCK | FAILED
    mode:       str   # human-readable source description
    duration_s: float
    insights:   list[dict]

    # Optional fields — agents include what's relevant
    raw_data:   NotRequired[dict]
    error:      NotRequired[str]


def result(
    *,
    name:       str,
    status:     str,
    mode:       str,
    duration_s: float,
    insights:   list[dict],
    **extra:    Any,
) -> AgentResult:
    return {
        "agent":      name,
        "status":     status,
        "mode":       mode,
        "duration_s": round(duration_s, 2),
        "insights":   insights,
        **extra,
    }


@contextmanager
def timer():
    """Usage:
        with timer() as t:
            ...
        t.elapsed  # float seconds
    """
    class T:
        elapsed = 0.0
    t = T()
    start = time.time()
    try:
        yield t
    finally:
        t.elapsed = time.time() - start
