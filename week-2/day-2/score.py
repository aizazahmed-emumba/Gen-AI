"""
Week 2 - Day 2 (Course Day 7) - SCORE baseline vs optimized retrieval.

Metric: hit-rate@5. A retrieved chunk is a HIT if it literally contains a gold
phrase (strict — a loose keyword doesn't count). Traps are excluded from the rate
(no correct chunk exists). For COMPOUND questions we require EVERY sub-answer to
be covered somewhere in the top-5 — one fact out of two is still a miss, which is
exactly the bar sub-query decomposition has to clear.
"""

import json
from pathlib import Path

DAY_DIR = Path(__file__).parent
RETRIEVERS = ["baseline", "multiquery", "hyde", "filtered", "optimized"]


def phrase_in(docs, phrases):
    """Rank (1-based) of the first top-k doc containing any phrase; None if miss."""
    for rank, d in enumerate(docs, 1):
        low = d["doc"].lower()
        if any(p.lower() in low for p in phrases):
            return rank
    return None


def judge(item, docs):
    """Return (is_hit, detail) for one question against one retriever's top-k."""
    if item["category"] == "compound":
        covered = []
        for sub in item["sub_questions"]:
            covered.append(phrase_in(docs, sub["gold_phrases"]) is not None)
        return all(covered), f"{sum(covered)}/{len(covered)} facts"
    rank = phrase_in(docs, item["gold_phrases"])
    return rank is not None, (f"rank {rank}" if rank else "miss")


def main():
    test_set = {it["id"]: it for it in json.loads((DAY_DIR / "test_set.json").read_text())}
    run = json.loads((DAY_DIR / "run_results.json").read_text())["results"]

    scored, totals = [], {r: 0 for r in RETRIEVERS}
    n_answerable = 0

    for row in run:
        item = test_set[row["id"]]
        is_trap = item["category"] == "trap"
        if not is_trap:
            n_answerable += 1
        entry = {"id": row["id"], "category": row["category"],
                 "question": row["question"], "trap": is_trap, "judged": {}}
        for r in RETRIEVERS:
            hit, detail = judge(item, row["retrieval"][r])
            entry["judged"][r] = {"hit": hit, "detail": detail}
            if hit and not is_trap:
                totals[r] += 1
        scored.append(entry)

    # ---- headline table ----
    print(f"\nhit-rate@5 over {n_answerable} answerable questions "
          f"(2 traps excluded):\n")
    print(f"  {'retriever':<12} {'hits':>6}  rate")
    for r in RETRIEVERS:
        print(f"  {r:<12} {totals[r]:>3}/{n_answerable}   {totals[r]/n_answerable:.0%}")

    # ---- per-question matrix ----
    print("\nper-question (rank of first correct chunk, or miss):\n")
    hdr = f"  {'id':<4} {'cat':<11} " + " ".join(f"{r[:8]:>9}" for r in RETRIEVERS)
    print(hdr)
    for e in scored:
        cells = " ".join(f"{(e['judged'][r]['detail'] if not e['trap'] else '-'):>9}" for r in RETRIEVERS)
        print(f"  {e['id']:<4} {e['category']:<11} {cells}")

    # ---- wins: baseline missed, optimized hit ----
    wins = [e for e in scored if not e["trap"]
            and not e["judged"]["baseline"]["hit"] and e["judged"]["optimized"]["hit"]]
    print(f"\nWINS (baseline miss -> optimized hit): {len(wins)}")
    for e in wins:
        print(f"  {e['id']}: {e['question'][:70]}")

    # ---- failures: optimization did NOT help (miss, or regressed) ----
    fails = [e for e in scored if not e["trap"]
             and (not e["judged"]["optimized"]["hit"]
                  or (e["judged"]["baseline"]["hit"] and not e["judged"]["optimized"]["hit"]))]
    print(f"\nFAILURES (optimized still miss): {len(fails)}")
    for e in fails:
        print(f"  {e['id']}: base={e['judged']['baseline']['detail']} "
              f"opt={e['judged']['optimized']['detail']} | {e['question'][:60]}")

    (DAY_DIR / "scoring_results.json").write_text(
        json.dumps({"totals": totals, "n_answerable": n_answerable, "scored": scored},
                   ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'scoring_results.json'}")


if __name__ == "__main__":
    main()
