"""Angle 5 of ANALYSIS.md: what the leads actually said.

Hundreds of real LLM-generated memory summaries exist in the sidecar logs
and had never been read as data before this pass - only spot-checked for
"does the sidecar work at all." This scores each summary's sentiment
(VADER, well-suited to short informal text like these) and checks it
against the lead's actual mechanical performance at that moment
(trade_success_ratio, hunger_scares_witnessed) - is there a gap between
self-perception and reality, and if so, in which direction?

Usage: python3 analyze_llm_narratives.py sidecar/logs/decisions.jsonl [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()


def load(path: Path) -> tuple[list[dict], list[dict]]:
    memories, decisions = [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn write from a killed process, not real data loss
            (memories if e["kind"] == "memory" else decisions).append(e)
    return memories, decisions


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")
    memories, decisions = load(path)
    print(f"{len(memories)} real memory summaries, {len(decisions)} real decisions")

    answered = sum(1 for d in decisions if d.get("llm_answered"))
    print(f"LLM actually answered {answered}/{len(decisions)} decision prompts ({answered/len(decisions):.1%}) - the rest fell back to mechanical autopilot")

    scored = []
    for m in memories:
        text = m.get("summary", "")
        if not text:
            continue
        sentiment = analyzer.polarity_scores(text)["compound"]
        ratio = m.get("trade_success_ratio")
        scares = m.get("hunger_scares_witnessed", 0)
        scored.append({"lead": m["lead_id"], "sentiment": sentiment, "ratio": ratio, "scares": scares, "text": text})

    with_ratio = [s for s in scored if s["ratio"] is not None]
    sentiments = np.array([s["sentiment"] for s in with_ratio])
    ratios = np.array([s["ratio"] for s in with_ratio])
    scares_arr = np.array([s["scares"] for s in with_ratio])

    print(f"\nmean sentiment: {sentiments.mean():+.3f} (VADER compound, -1 very negative to +1 very positive)")
    r1, p1 = stats.spearmanr(sentiments, ratios)
    r2, p2 = stats.spearmanr(sentiments, scares_arr)
    print(f"sentiment vs actual trade_success_ratio: rho={r1:+.3f} (p={p1:.3g})")
    print(f"sentiment vs hunger_scares_witnessed:     rho={r2:+.3f} (p={p2:.3g})")

    # overconfidence: very positive sentiment despite a poor real trade ratio
    overconfident = sorted(with_ratio, key=lambda s: s["sentiment"] - s["ratio"], reverse=True)[:3]
    print("\nmost overconfident (positive tone, poor actual trade ratio):")
    for s in overconfident:
        print(f"  {s['lead']} (ratio={s['ratio']:.2f}, sentiment={s['sentiment']:+.2f}): \"{s['text'][:140]}\"")

    undersold = sorted(with_ratio, key=lambda s: s["ratio"] - s["sentiment"], reverse=True)[:3]
    print("\nmost undersold (negative/flat tone despite a strong actual trade ratio):")
    for s in undersold:
        print(f"  {s['lead']} (ratio={s['ratio']:.2f}, sentiment={s['sentiment']:+.2f}): \"{s['text'][:140]}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_llm_narratives.py decisions.jsonl [decisions2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
