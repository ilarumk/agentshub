#!/usr/bin/env python3
"""
Quick CLI to test any agent or run all agents on a topic.

Usage:
    python run.py list                              # show available agents
    python run.py news_trending skincare            # single agent
    python run.py social_trends instagram reels     # single agent, multi-word topic
    python run.py youtube_shorts --shorts skincare  # with shorts filter
    python run.py wikipedia_spike --topics Retinol Niacinamide
    python run.py all skincare                      # fan-out all agents on one topic
    python run.py instagram                         # shortcut: Instagram trend report
    python run.py tiktok                            # shortcut: TikTok trend report
"""

import sys
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from agentshub.agents import REGISTRY, get_run, list_agents
from agentshub.orchestrator import run_parallel


def _print_result(name, res, wall=None):
    status = res.get("status", "?")
    mode   = res.get("mode", "")[:50]
    dur    = res.get("duration_s", 0)
    wall_s = f"  wall={wall:.1f}s" if wall else ""
    print(f"  {name:<20} [{status:<7}] {dur:.1f}s{wall_s}  {mode}")


def cmd_list():
    print("\nAvailable agents:\n")
    for a in list_agents():
        params = ", ".join(a["params"].keys()) if a["params"] else "none"
        print(f"  {a['name']:<20} params: {params}")
        print(f"  {'':20} {a['description'][:70]}")
        print()


def cmd_single(agent_name, topic, extra_args):
    run_fn = get_run(agent_name)

    # Build kwargs based on agent
    kwargs = {}
    if agent_name == "wikipedia_spike":
        if "--topics" in extra_args:
            idx = extra_args.index("--topics")
            kwargs["topics"] = extra_args[idx + 1:]
        elif topic:
            kwargs["topics"] = [topic]
    elif agent_name == "youtube_shorts":
        kwargs["topic"] = topic
        kwargs["shorts_only"] = "--shorts" in extra_args
    elif agent_name == "social_trends":
        # First word = platform, rest = topic
        kwargs["platform"] = topic
        rest = " ".join(extra_args) if extra_args else "trends"
        kwargs["topic"] = rest
    elif agent_name == "rising_search":
        kwargs["topic"] = topic
    elif agent_name == "news_trending":
        kwargs["topic"] = topic
    else:
        kwargs["topic"] = topic

    print(f"\n  Running {agent_name}({kwargs})...\n")
    result = run_fn(**kwargs)
    _print_result(agent_name, result)
    print()
    print(json.dumps(result, indent=2, default=str))


def cmd_all(topic):
    plan = [
        ("social_trends",  {"platform": "instagram", "topic": f"{topic} trends"}),
        ("news_trending",  {"topic": topic, "days": 14, "limit": 15}),
        ("youtube_shorts", {"topic": topic, "shorts_only": True}),
        ("rising_search",  {"topic": topic, "limit": 10}),
    ]

    print(f"\n  Running all agents for '{topic}' in parallel...\n")
    def cb(name, res, wall):
        _print_result(name, res, wall)

    results = run_parallel(plan, on_result=cb)

    # Summary
    print(f"\n{'─'*60}")
    for name, res in results.items():
        for ins in res.get("insights", []):
            print(f"  [{name}] {ins.get('type','')}: {ins.get('finding','')}")

        if name == "social_trends":
            for p in res.get("posts", [])[:5]:
                print(f"    · [{p['site'][:18]}] {p['title'][:50]}")
        elif name == "news_trending":
            for a in res.get("articles", [])[:3]:
                print(f"    · [{a['source'][:18]}] {a['title'][:50]}")
        elif name == "youtube_shorts":
            for v in res.get("videos", [])[:3]:
                print(f"    · {v['views']:>10,} views  {v['title'][:45]}")
    print(f"{'─'*60}")


def cmd_platform(platform):
    plan = [
        ("social_trends",  {"platform": platform, "topic": "trends", "days": 30, "limit": 10}),
        ("social_trends",  {"platform": platform, "topic": "trending audio music", "days": 30, "limit": 8}),
        ("youtube_shorts", {"topic": f"{platform} trends 2026", "shorts_only": True}),
        ("news_trending",  {"topic": f"{platform} viral trends", "days": 14, "limit": 8}),
    ]

    # De-dup social_trends → run audio query separately
    parallel_plan = [plan[0], plan[2], plan[3]]

    print(f"\n  {platform.upper()} TREND REPORT")
    print(f"  {'─'*50}\n")

    def cb(name, res, wall):
        _print_result(name, res, wall)

    results = run_parallel(parallel_plan, on_result=cb)

    # Audio query
    print("  Fetching trending audio...")
    audio = get_run("social_trends")(**plan[1][1])
    _print_result("social_trends/audio", audio)

    # Report
    st = results.get("social_trends", {})
    yt = results.get("youtube_shorts", {})
    nw = results.get("news_trending", {})

    print(f"\n{'═'*60}")
    print(f"  TREND REPORTS from marketing blogs")
    print(f"{'─'*60}")
    for p in st.get("posts", [])[:8]:
        print(f"  · [{p['site'][:18]:<18}] {p['title'][:45]}")
    print()

    print(f"  TRENDING AUDIO blogs")
    print(f"{'─'*60}")
    for p in audio.get("posts", [])[:6]:
        print(f"  · [{p['site'][:18]:<18}] {p['title'][:45]}")
    print()

    if yt.get("videos"):
        print(f"  YOUTUBE validation (what's getting views)")
        print(f"{'─'*60}")
        for v in yt["videos"][:5]:
            print(f"  · {v['views']:>10,}  [{v['duration_s']:>2}s] {v['title'][:42]}")
        print()

    if nw.get("articles"):
        print(f"  NEWS coverage")
        print(f"{'─'*60}")
        for a in nw["articles"][:5]:
            print(f"  · [{a['source'][:18]:<18}] {a['title'][:45]}")

    print(f"\n{'═'*60}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return

    cmd = args[0]

    if cmd == "list":
        cmd_list()
    elif cmd == "all" and len(args) > 1:
        cmd_all(" ".join(args[1:]))
    elif cmd in ("instagram", "tiktok", "reels"):
        cmd_platform(cmd)
    elif cmd in [a["name"] for a in REGISTRY]:
        topic = args[1] if len(args) > 1 else ""
        extra = args[2:] if len(args) > 2 else []
        cmd_single(cmd, topic, extra)
    else:
        # Treat entire input as a topic for "all"
        cmd_all(" ".join(args))


if __name__ == "__main__":
    main()
