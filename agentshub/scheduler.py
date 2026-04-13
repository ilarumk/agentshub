"""
Scheduler — runs a topic watch list at a fixed interval and writes
spike alerts to a markdown digest (e.g. an Obsidian vault).

Usage:
    agentshub-schedule --topic skincare --interval 21600  # 6 hours
    agentshub-schedule --topic "ev batteries" --topic "weight loss" --once

Run via cron, launchd, or as a long-running process.
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agentshub.orchestrator import run_parallel

# Load env from package root
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_PACKAGE_DIR / ".env")

DEFAULT_DIGEST = Path.home() / "Obsidian" / "trends" / "digest.md"


def _build_plan(topic: str) -> list[tuple[str, dict]]:
    """For a given topic, decide which agents to fan out to."""
    return [
        ("news_trending",   {"topic": topic, "days": 7, "limit": 15}),
        ("youtube_shorts",  {"topic": topic, "shorts_only": True}),
        ("rising_search",   {"topic": topic, "limit": 15}),
        # wikipedia_spike skipped — needs explicit topic list, not free-text
    ]


def _format_digest(topic: str, results: dict[str, dict]) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"## {topic} — {ts}", ""]

    for name, res in results.items():
        status = res.get("status", "?")
        mode   = res.get("mode", "")
        out.append(f"### {name}  `{status}`")
        out.append(f"_{mode}_")
        out.append("")
        for ins in res.get("insights", []):
            line = f"- **{ins.get('type','')}**: {ins.get('finding','')}"
            out.append(line)
            if "themes" in ins:
                themes = ", ".join(f"{t['word']}({t['count']})" for t in ins["themes"][:5])
                out.append(f"  - themes: {themes}")
            if "topics" in ins:
                out.append(f"  - {', '.join(ins['topics'][:5])}")

        # Concrete top items per agent
        if name == "news_trending" and res.get("articles"):
            out.append("")
            out.append("  Top 3 articles:")
            for a in res["articles"][:3]:
                out.append(f"  - [{a['source']}] {a['title']}")
        elif name == "youtube_shorts" and res.get("videos"):
            out.append("")
            out.append("  Top 3 shorts:")
            for v in res["videos"][:3]:
                out.append(f"  - [{v['views']:,} views] {v['title']}")

        out.append("")

    out.append("---")
    out.append("")
    return "\n".join(out)


def _append_digest(digest_path: Path, content: str) -> None:
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    with digest_path.open("a", encoding="utf-8") as f:
        f.write(content)


def run_once(topic: str, digest_path: Path) -> None:
    print(f"[{datetime.now():%H:%M:%S}] running watch for: {topic}")

    def cb(name, res, wall):
        print(f"  {wall:5.1f}s  {name:<18} [{res.get('status','?')}]")

    plan    = _build_plan(topic)
    results = run_parallel(plan, on_result=cb)

    digest = _format_digest(topic, results)
    _append_digest(digest_path, digest)
    print(f"  → wrote digest to {digest_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic",    action="append", required=True,
                        help="Topic to watch (can pass multiple times)")
    parser.add_argument("--interval", type=int, default=21600,
                        help="Seconds between runs (default 6h)")
    parser.add_argument("--once",     action="store_true",
                        help="Run once and exit instead of looping")
    parser.add_argument("--digest",   type=Path, default=DEFAULT_DIGEST,
                        help=f"Markdown digest file (default {DEFAULT_DIGEST})")
    args = parser.parse_args()

    if args.once:
        for topic in args.topic:
            run_once(topic, args.digest)
        return

    while True:
        for topic in args.topic:
            run_once(topic, args.digest)
        print(f"[sleep {args.interval}s]")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
