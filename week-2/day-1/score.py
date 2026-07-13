"""
Score retrieval quality for the three chunking strategies.

Metric: hit-rate@5. For each answerable question we know a `gold_phrase` that
appears ONLY where the real answer is. A retrieved chunk is "relevant" iff it
contains that phrase. hit@5 = a relevant chunk is among the top-5 retrieved.

We also record the RANK of the first relevant chunk (1..10, or "miss" if it is
not in the top-10). Rank lets us see improvement even when both strategies hit -
e.g. the answer moving from rank 4 to rank 1 is still better retrieval.
"""

import json
import re
from pathlib import Path

DAY_DIR = Path(__file__).parent
STRATEGIES = ["fixed", "overlapping", "recursive"]
MISS = 99  # sentinel rank for "not found in top-10", so arithmetic works


def norm(t):
    return re.sub(r"\s+", " ", t.lower())


def first_relevant_rank(documents, gold_phrases):
    """1-based rank of the first retrieved chunk containing any gold phrase."""
    gps = [norm(g) for g in gold_phrases]
    for rank, doc in enumerate(documents, start=1):
        nd = norm(doc)
        if any(g in nd for g in gps):
            return rank
    return MISS


def main():
    data = json.loads((DAY_DIR / "run_results.json").read_text(encoding="utf-8"))
    top_k = data["top_k"]
    rows = []
    for r in data["results"]:
        if not r["answerable"]:
            continue  # traps have no relevant chunk -> excluded from hit-rate
        ranks = {s: first_relevant_rank(r["retrieval"][s]["documents"], r["gold_phrases"])
                 for s in STRATEGIES}
        rows.append({"id": r["id"], "position": r["doc_position"],
                     "question": r["question"], "ranks": ranks})

    n = len(rows)

    def rank_str(rk):
        return "miss" if rk == MISS else str(rk)

    # ── per-question rank table ──────────────────────────────────────────────
    print(f"\nRank of first relevant chunk (1 = top result, 'miss' = not in top-{top_k})")
    print(f"{'Q':<4}{'position':<20}{'fixed':<9}{'overlap':<9}{'recursive':<10}")
    print("-" * 52)
    for row in rows:
        rk = row["ranks"]
        print(f"{row['id']:<4}{row['position']:<20}"
              f"{rank_str(rk['fixed']):<9}{rank_str(rk['overlapping']):<9}{rank_str(rk['recursive']):<10}")

    # ── hit-rate@k summary ───────────────────────────────────────────────────
    def hit_rate(k):
        return {s: sum(1 for row in rows if row["ranks"][s] <= k) for s in STRATEGIES}

    print(f"\n{'hit-rate':<12}" + "".join(f"{s:<12}" for s in STRATEGIES))
    print("-" * 48)
    for k in (1, 3, 5):
        hr = hit_rate(k)
        print(f"@{k:<11}" + "".join(f"{hr[s]}/{n} ({hr[s]/n:.0%}){'':<3}" for s in STRATEGIES))

    # ── recursive (advanced) vs fixed (baseline) ─────────────────────────────
    print("\nRecursive vs fixed  (delta = fixed_rank - recursive_rank; + = recursive better)")
    diffs = []
    for row in rows:
        f, r = row["ranks"]["fixed"], row["ranks"]["recursive"]
        diffs.append({"id": row["id"], "position": row["position"],
                      "question": row["question"],
                      "fixed": f, "recursive": r, "delta": f - r})

    improved = sorted([d for d in diffs if d["delta"] > 0], key=lambda d: -d["delta"])
    worse = sorted([d for d in diffs if d["delta"] < 0], key=lambda d: d["delta"])
    same = [d for d in diffs if d["delta"] == 0]

    print(f"\n  IMPROVED by recursive ({len(improved)}):")
    for d in improved:
        print(f"    {d['id']:<4} fixed {rank_str(d['fixed'])} -> recursive {rank_str(d['recursive'])}   {d['position']}")
    print(f"\n  WORSE with recursive ({len(worse)}):")
    for d in worse:
        print(f"    {d['id']:<4} fixed {rank_str(d['fixed'])} -> recursive {rank_str(d['recursive'])}   {d['position']}")
    print(f"\n  UNCHANGED ({len(same)}): {', '.join(d['id'] for d in same)}")

    out = {"n_answerable": n, "top_k": top_k,
           "hit_rate_at": {str(k): hit_rate(k) for k in (1, 3, 5)},
           "rows": rows, "recursive_vs_fixed": diffs}
    (DAY_DIR / "scoring_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved -> {DAY_DIR / 'scoring_results.json'}")


if __name__ == "__main__":
    main()
