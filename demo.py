#!/usr/bin/env python3
"""
Multi-agent demo — sequential vs parallel execution with timing,
sub-agent visibility, and per-agent detail.

Usage:
    cd ~/projects/agentshub
    source .venv/bin/activate
    python demo.py
"""

import time
import json
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from agentshub.orchestrator import run_parallel, run_sequential

W = 70

def ts():
    return datetime.now().strftime("%H:%M:%S")

def hr(c="─"):
    print(c * W)

def header(text):
    print(f"\n{'═' * W}")
    print(f"  {text}")
    print(f"{'═' * W}\n")

def on_result(name, result, wall_s):
    status = result.get("status", "?")
    mode = result.get("mode", "")
    dur = result.get("duration_s", 0)

    # Count output items
    insights = result.get("insights", [])
    articles = result.get("articles", [])
    posts = result.get("posts", [])
    terms = result.get("terms", [])
    items = insights or articles or posts or terms
    n = len(items)

    # Detect sub-agent usage
    has_sub_agent = result.get("extracted") is not None
    sub_label = "  ↳ spawned sub-agent (GPT-4o-mini)" if has_sub_agent else ""

    print(f"  [{ts()}] ✓ {name:20s}  {dur:5.1f}s  |  wall: {wall_s:5.1f}s  |  {n} insights")
    print(f"           mode: {mode}")
    if sub_label:
        print(f"          {sub_label}")


def print_agent_detail(name, result):
    """Print what each agent actually produced."""
    hr()
    print(f"  Agent: {name}")
    print(f"  Status: {result.get('status')}  |  Duration: {result.get('duration_s', 0):.1f}s")
    print(f"  Mode: {result.get('mode')}")

    # Data sources accessed
    query = result.get("query", "")
    if query:
        print(f"  Query: {query}")

    # Sub-agent info
    extracted = result.get("extracted")
    if extracted:
        n_trends = len(extracted.get("trends", []))
        n_audio = len(extracted.get("audio", []))
        n_tips = len(extracted.get("tips", []))
        print(f"  Sub-agent: GPT-4o-mini → extracted {n_trends} trends, {n_audio} audio, {n_tips} tips")

    # Insights summary
    insights = result.get("insights", [])
    for ins in insights[:4]:
        finding = ins.get("finding", "")
        if len(finding) > 80:
            finding = finding[:77] + "..."
        print(f"    • [{ins.get('type', '?')}] {finding}")

    # Sample output items
    posts = result.get("posts", [])
    articles = result.get("articles", [])
    terms = result.get("terms", [])
    items = posts or articles or terms
    if items:
        print(f"  Sample data ({len(items)} total):")
        for item in items[:3]:
            if isinstance(item, dict):
                label = item.get("title", item.get("term", str(item)))
                if len(label) > 60:
                    label = label[:57] + "..."
                site = item.get("site", item.get("source", ""))
                print(f"    → {label}" + (f"  [{site}]" if site else ""))
    print()


def main():
    topic = "AI"
    plan = [
        ("rising_search", {}),
        ("news_trending", {"topic": topic, "days": 7, "limit": 10}),
        ("social_trends", {"platform": "instagram", "topic": topic, "days": 30, "limit": 10}),
    ]

    agent_names = [name for name, _ in plan]

    header(f"MULTI-AGENT DEMO — topic: '{topic}'")
    print(f"  Agents: {', '.join(agent_names)}")
    print(f"  Each agent hits a different data source independently.")
    print(f"  social_trends spawns an internal sub-agent (GPT-4o-mini) for extraction.\n")

    # ── Sequential ─────────────────────────────────────────────
    header("RUN 1: SEQUENTIAL — agents run one after another")
    seq_start = time.time()
    print(f"  [{ts()}] Starting sequential run...\n")

    seq_results = run_sequential(plan, on_result=on_result)

    seq_total = time.time() - seq_start
    print(f"\n  Sequential total: {seq_total:.1f}s")

    # ── Parallel ───────────────────────────────────────────────
    header("RUN 2: PARALLEL — all agents fire at once")
    par_start = time.time()
    print(f"  [{ts()}] Starting parallel run...\n")

    par_results = run_parallel(plan, on_result=on_result)

    par_total = time.time() - par_start
    print(f"\n  Parallel total: {par_total:.1f}s")

    # ── Comparison ─────────────────────────────────────────────
    header("TIMING COMPARISON")

    speedup = seq_total / par_total if par_total > 0 else 0
    saved = seq_total - par_total

    print(f"  Sequential:  {seq_total:5.1f}s  (each agent waits for the previous)")
    print(f"  Parallel:    {par_total:5.1f}s  (wall-clock = slowest agent)")
    print(f"  Speedup:     {speedup:.1f}x  ({saved:.1f}s saved)")
    print()

    # Per-agent breakdown
    print(f"  Per-agent timing (parallel run):")
    for name in agent_names:
        res = par_results.get(name, {})
        dur = res.get("duration_s", 0)
        has_sub = "  + sub-agent" if res.get("extracted") else ""
        print(f"    {name:20s}  {dur:5.1f}s{has_sub}")
    print()

    # ── Agent details ──────────────────────────────────────────
    header("WHAT EACH AGENT RETURNED")

    for name in agent_names:
        print_agent_detail(name, par_results.get(name, {}))

    # ── Synthesis ──────────────────────────────────────────────
    header("SYNTHESIS — reasoning agent cross-references all outputs")

    print(f"  Pipeline flow:")
    print(f"    User query: '{topic}'")
    print(f"         │")
    print(f"         ├─→ rising_search     [BigQuery Google Trends]")
    print(f"         ├─→ news_trending     [Google News RSS]")
    print(f"         └─→ social_trends     [10 marketing blogs]")
    print(f"              └─→ sub-agent    [GPT-4o-mini extraction]")
    print(f"         │")
    print(f"         ▼")
    print(f"    Synthesizer (GPT-4o-mini) merging outputs...\n")

    # Build a compact summary of each agent's output for the synthesizer
    agent_summaries = {}
    for name, res in par_results.items():
        summary_parts = []
        for ins in res.get("insights", []):
            summary_parts.append(f"- {ins.get('type', '?')}: {ins.get('finding', '')}")
        # Add sample titles
        items = res.get("posts", []) or res.get("articles", []) or res.get("terms", [])
        if items:
            titles = [i.get("title", i.get("term", "")) for i in items[:5]]
            summary_parts.append(f"- sample items: {'; '.join(titles)}")
        # Add extracted trends if present
        extracted = res.get("extracted", {})
        if extracted and "trends" in extracted:
            for t in extracted["trends"][:3]:
                summary_parts.append(f"- trend: {t.get('name', '')} — {t.get('description', '')}")
        agent_summaries[name] = "\n".join(summary_parts)

    synth_prompt = f"""You are a trend intelligence synthesizer. Three agents independently gathered data about '{topic}'.
Cross-reference their outputs and produce a brief (under 200 words) that answers:
1. What signals appear across multiple sources? (high confidence)
2. What's trending in search/news but missing from social? (early signal)
3. What's on social but absent from search/news? (niche or emerging)
4. One actionable takeaway.

Agent outputs:

RISING_SEARCH (Google Trends — nationally rising search terms):
{agent_summaries.get('rising_search', 'no data')}

NEWS_TRENDING (Google News — recent articles):
{agent_summaries.get('news_trending', 'no data')}

SOCIAL_TRENDS (Marketing blogs — platform-specific trends):
{agent_summaries.get('social_trends', 'no data')}

Be specific. Name the signals. Keep it concise."""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        synth_start = time.time()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": synth_prompt}],
            max_tokens=400,
            temperature=0.3,
        )
        synth_time = time.time() - synth_start
        briefing = resp.choices[0].message.content.strip()
        tokens_used = resp.usage.total_tokens if resp.usage else 0

        print(f"  [{ts()}] Synthesizer done in {synth_time:.1f}s ({tokens_used} tokens)\n")
        hr()
        print(f"\n  BRIEFING: '{topic}' — {datetime.now().strftime('%Y-%m-%d')}\n")
        for line in briefing.split("\n"):
            print(f"  {line}")
        print()
        hr()

    except Exception as exc:
        print(f"  Synthesis failed: {exc}")
        print(f"  (Set OPENAI_API_KEY in .env to enable the synthesizer)\n")

    # ── Final summary ──────────────────────────────────────────
    header("SUMMARY")
    print(f"  3 data agents gathered signals in {par_total:.1f}s (parallel)")
    print(f"  1 synthesizer reasoned across all outputs in {synth_time:.1f}s")
    print(f"  social_trends internally spawned a sub-agent for extraction")
    print(f"  Total pipeline: {par_total + synth_time:.1f}s end-to-end")
    print()
    hr("═")


if __name__ == "__main__":
    main()
