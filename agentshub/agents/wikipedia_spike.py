"""
Wikipedia Spike Agent — Wikimedia Pageviews REST API.

For a list of article titles, computes the ratio of recent pageviews against
a baseline period. High ratios = spike. Free, no auth required.

Strongest free leading signal for cultural / celebrity / event-driven trends.
"""

import json
import urllib.request
import urllib.parse
from datetime import date, timedelta
from agentshub.base import result, timer

NAME = "wikipedia_spike"

PAGEVIEW_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/all-agents/{title}/daily/{start}/{end}"
)
HEADERS = {"User-Agent": "agentshub/0.1 (learning prototype)"}


def _fetch_views(title: str, start: str, end: str) -> list[int]:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url     = PAGEVIEW_URL.format(title=encoded, start=start, end=end)
    req     = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read())
    return [item["views"] for item in data.get("items", [])]


def _spike_ratio(views: list[int], recent_days: int = 3) -> float:
    """Compare avg of last `recent_days` against baseline of earlier days."""
    if len(views) < recent_days + 3:
        return 0.0
    recent   = views[-recent_days:]
    baseline = views[:-recent_days]
    avg_recent   = sum(recent)   / len(recent)
    avg_baseline = sum(baseline) / max(len(baseline), 1)
    if avg_baseline == 0:
        return 0.0
    return round(avg_recent / avg_baseline, 2)


def run(topics: list[str] | None = None, days: int = 14) -> dict:
    with timer() as t:
        # Default sample list — caller should pass topics for real use
        if not topics:
            topics = ["Niacinamide", "Retinol", "Glycolic_acid"]

        end_date   = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)
        start      = start_date.strftime("%Y%m%d")
        end        = end_date.strftime("%Y%m%d")

        spikes = []
        errors = []
        for title in topics:
            try:
                views = _fetch_views(title, start, end)
                if not views:
                    continue
                ratio = _spike_ratio(views, recent_days=3)
                spikes.append({
                    "title":         title,
                    "spike_ratio":   ratio,
                    "recent_avg":    int(sum(views[-3:]) / 3) if len(views) >= 3 else 0,
                    "baseline_avg":  int(sum(views[:-3]) / max(len(views) - 3, 1)),
                    "is_spike":      ratio >= 1.5,
                })
            except Exception as exc:
                errors.append(f"{title}: {exc}")

        spikes.sort(key=lambda s: s["spike_ratio"], reverse=True)
        active_spikes = [s for s in spikes if s["is_spike"]]

        return result(
            name       = NAME,
            status     = "SUCCESS" if spikes else "FAILED",
            mode       = f"LIVE — Wikimedia Pageviews ({start}→{end})",
            duration_s = t.elapsed,
            insights   = [
                {
                    "type":    "pageview spikes",
                    "finding": f"{len(active_spikes)}/{len(topics)} topics spiking (≥1.5x baseline)",
                    "topics":  [s["title"] for s in active_spikes[:5]],
                }
            ],
            spikes     = spikes,
            errors     = errors,
        )
