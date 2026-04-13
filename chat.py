#!/usr/bin/env python3
"""
Interactive trend chat — ask questions, agents fire automatically.

Usage:
    cd ~/projects/agentshub
    source .venv/bin/activate
    python chat.py

Then ask anything:
    > what's trending on instagram reels this week?
    > are there any skincare ingredients spiking on wikipedia?
    > what youtube shorts are going viral about weight loss?
    > exit
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from openai import OpenAI
from agentshub.agents import REGISTRY, get_run

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Build OpenAI function definitions from the agent registry
TOOLS = []
for meta in REGISTRY:
    properties = {}
    for pname, pdesc in meta["params"].items():
        ptype = pdesc.get("type", "string")
        prop  = {"type": ptype, "description": pdesc.get("description", "")}
        if ptype == "array":
            prop["items"] = {"type": "string"}
        properties[pname] = prop

    TOOLS.append({
        "type": "function",
        "function": {
            "name":        meta["name"],
            "description": meta["description"],
            "parameters":  {
                "type":       "object",
                "properties": properties,
            },
        },
    })

SYSTEM = """You are a trend research assistant. You have access to these live data tools:

- rising_search: Returns ALL nationally rising + popular Google search terms this week (no params).
  The list is ~30 rising + 25 popular terms. YOU scan the list and pick out which terms
  relate to the user's topic. e.g. if user asks about food and you see "gonzo cheese" or
  "carolina reaper" in the rising list, flag those.
- wikipedia_spike: detect Wikipedia pageview spikes for specific article titles
- news_trending: Google News articles by topic keyword. Returns headlines, sources, and
  full article text when available. Use the article content for deeper analysis.
- youtube_shorts: trending YouTube videos, can filter to shorts (<60s)
- social_trends: curated marketing blog aggregator (Sprout Social, Hootsuite, Later, etc.)
  Returns structured data including: extracted trend names with descriptions, trending
  audio tracks (song + artist + mood), and actionable tips. ALWAYS include these details
  in your response — they are the most valuable part of this tool's output.

When the user asks about trends, call multiple tools at once for cross-source signal.
Keep your answers detailed and actionable. Lead with what's trending, cite which source
confirmed it, include specific trend names, audio tracks, and tips from the data.
When generating newsletters or reports, use the full richness of the data — article excerpts,
specific trend names, audio recommendations, platform-specific tips.
If a tool returns no results, say so honestly — it means the topic isn't spiking nationally this week.
"""

def _run_tool(name: str, args: dict) -> str:
    try:
        run_fn = get_run(name)
        result = run_fn(**args)
        # Trim raw data to keep context manageable
        trimmed = {k: v for k, v in result.items()
                   if k not in ("raw_data",)}
        # Truncate long lists
        for key in ("articles", "posts", "videos", "terms", "spikes"):
            if key in trimmed and isinstance(trimmed[key], list):
                trimmed[key] = trimmed[key][:8]
        return json.dumps(trimmed, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def chat(question: str, history: list[dict]) -> str:
    messages = [{"role": "system", "content": SYSTEM}] + history
    messages.append({"role": "user", "content": question})

    # First call — LLM decides which tools to use
    resp = client.chat.completions.create(
        model    = "gpt-4o-mini",
        messages = messages,
        tools    = TOOLS,
        tool_choice = "auto",
    )
    msg = resp.choices[0].message

    # If no tool calls, return the text directly
    if not msg.tool_calls:
        return msg.content or "(no response)"

    # Execute all tool calls in parallel — the model planned the fan-out,
    # the code should honor it
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print(f"\n  agents firing:")
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        print(f"    → {tc.function.name}({', '.join(f'{k}={v!r}' for k,v in args.items())})")

    tool_results = [None] * len(msg.tool_calls)
    with ThreadPoolExecutor(max_workers=len(msg.tool_calls)) as pool:
        future_to_idx = {}
        for i, tc in enumerate(msg.tool_calls):
            args = json.loads(tc.function.arguments)
            future = pool.submit(_run_tool, tc.function.name, args)
            future_to_idx[future] = (i, tc)

        for future in as_completed(future_to_idx):
            i, tc = future_to_idx[future]
            tool_results[i] = {
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      future.result(),
            }

    # Second call — LLM synthesizes results
    messages.append(msg)
    messages.extend(tool_results)

    synth = client.chat.completions.create(
        model    = "gpt-4o-mini",
        messages = messages,
    )
    return synth.choices[0].message.content or "(no response)"


def main():
    print("\n  agentshub chat — ask about trends, agents fire automatically")
    print("  type 'exit' to quit\n")

    history: list[dict] = []

    while True:
        try:
            q = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  bye")
            break

        if not q:
            continue
        if q.lower() in ("exit", "quit", "q"):
            print("  bye")
            break

        answer = chat(q, history)

        # Keep conversation context (last 6 turns)
        history.append({"role": "user",      "content": q})
        history.append({"role": "assistant", "content": answer})
        if len(history) > 12:
            history = history[-12:]

        print(f"\n{answer}\n")


if __name__ == "__main__":
    main()
