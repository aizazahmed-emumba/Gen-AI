"""
Week 2 - Day 3 (Course Day 8) - SCORE and analyze.

Produces the three required tables:
  1. hit-rate@5     — vector vs bm25 vs hybrid       (did a gold-phrase chunk make top-5?)
  2. answer correctness   — none vs cross_encoder vs llm reranking
  3. citation accuracy    — none vs cross_encoder vs llm reranking
plus the analysis: hybrid wins over vector, and reranking wins over no-rerank.

Chunk text is rehydrated from the collection so gold-phrase checks use the real
chunk content, not whatever was truncated into run_results.json.
"""

import json
import re
from pathlib import Path

import retrieve

# gpt-oss cites with several bracket styles: [1], 【1】, [1†L1-L4]. Catch an opening
# bracket ([ or 【) immediately followed by digits — re-derived from the answer text
# so a parser miss at generation time doesn't corrupt citation scoring.
_CITE_RE = re.compile(r"[\[【](\d+)")


def parse_citations(answer, n):
    return sorted({int(m) for m in _CITE_RE.findall(answer) if 1 <= int(m) <= n})

DAY_DIR = Path(__file__).parent
RETRIEVERS = ["vector", "bm25", "hybrid"]
RERANKS = ["none", "cross_encoder", "llm"]


def has_gold(text, phrases):
    low = text.lower()
    return any(p.lower() in low for p in phrases)


def gold_rank(ids_list, lookup, phrases):
    for r, cid in enumerate(ids_list, 1):
        if has_gold(lookup[cid]["doc"], phrases):
            return r
    return None


def retrieval_hit(item, ids_list, lookup):
    """Compound = every sub-fact must appear somewhere in the list."""
    if item["category"] == "compound":
        return all(gold_rank(ids_list, lookup, sub["gold_phrases"]) is not None
                   for sub in item["sub_questions"])
    return gold_rank(ids_list, lookup, item["gold_phrases"]) is not None


def answer_correct(item, answer):
    if item["category"] == "trap":
        return "not in context" in answer.lower()
    if item["category"] == "compound":
        return all(has_gold(answer, sub["gold_phrases"]) for sub in item["sub_questions"])
    return has_gold(answer, item["gold_phrases"])


def citation_ok(item, variant, lookup):
    """A citation is accurate if a CITED chunk actually contains a gold phrase.
    For traps, accurate = the model cited nothing (it abstained)."""
    cited = parse_citations(variant["answer"], len(variant["top5"]))
    cited_ids = [variant["top5"][i - 1] for i in cited]
    if item["category"] == "trap":
        return len(cited_ids) == 0
    if not cited_ids:
        return False
    if item["category"] == "compound":
        # each fact must be supported by some cited chunk
        return all(any(has_gold(lookup[cid]["doc"], sub["gold_phrases"]) for cid in cited_ids)
                   for sub in item["sub_questions"])
    return any(has_gold(lookup[cid]["doc"], item["gold_phrases"]) for cid in cited_ids)


def main():
    test = {it["id"]: it for it in json.loads((DAY_DIR / "test_set.json").read_text())}
    run = json.loads((DAY_DIR / "run_results.json").read_text())["results"]
    lookup = retrieve.load()["lookup"]

    answerable = [r for r in run if test[r["id"]]["category"] != "trap"]
    n = len(answerable)

    # ---- Table 1: retrieval hit-rate@5 ----
    hit = {ret: 0 for ret in RETRIEVERS}
    for r in answerable:
        for ret in RETRIEVERS:
            if retrieval_hit(test[r["id"]], r["retrieval"][ret], lookup):
                hit[ret] += 1
    print(f"\n=== Table 1 — hit-rate@5 ({n} answerable) ===")
    for ret in RETRIEVERS:
        print(f"  {ret:<14} {hit[ret]:>2}/{n}  {hit[ret]/n:.0%}")

    # ---- Tables 2 & 3: correctness and citation accuracy by rerank ----
    correct = {rr: 0 for rr in RERANKS}
    cite = {rr: 0 for rr in RERANKS}
    for r in run:
        it = test[r["id"]]
        for rr in RERANKS:
            v = r["rerank"][rr]
            if it["category"] != "trap":
                if answer_correct(it, v["answer"]):
                    correct[rr] += 1
                if citation_ok(it, v, lookup):
                    cite[rr] += 1
    print(f"\n=== Table 2 — answer correctness ({n} answerable) ===")
    for rr in RERANKS:
        print(f"  {rr:<14} {correct[rr]:>2}/{n}  {correct[rr]/n:.0%}")
    print(f"\n=== Table 3 — citation accuracy ({n} answerable) ===")
    for rr in RERANKS:
        print(f"  {rr:<14} {cite[rr]:>2}/{n}  {cite[rr]/n:.0%}")

    # ---- Analysis: hybrid beats vector ----
    print("\n=== Hybrid improved over vector (per-question rank of first gold chunk) ===")
    hybrid_wins = []
    for r in answerable:
        it = test[r["id"]]
        phr = it["gold_phrases"] if it["category"] != "compound" else \
            [p for sub in it["sub_questions"] for p in sub["gold_phrases"]]
        rv = gold_rank(r["retrieval"]["vector"], lookup, phr)
        rh = gold_rank(r["retrieval"]["hybrid"], lookup, phr)
        rb = gold_rank(r["retrieval"]["bm25"], lookup, phr)
        better = (rh is not None and (rv is None or rh < rv))
        if better:
            hybrid_wins.append((r["id"], rv, rb, rh, r["question"][:52]))
    for w in hybrid_wins:
        print(f"  {w[0]:<4} vector={str(w[1]):<5} bm25={str(w[2]):<5} hybrid={str(w[3]):<5} | {w[4]}")

    # ---- Analysis: reranking changed the answer ----
    print("\n=== Reranking changed correctness/citation vs no-rerank ===")
    for r in run:
        it = test[r["id"]]
        base_c = answer_correct(it, r["rerank"]["none"]["answer"])
        base_cite = citation_ok(it, r["rerank"]["none"], lookup)
        for rr in ["cross_encoder", "llm"]:
            c = answer_correct(it, r["rerank"][rr]["answer"])
            ct = citation_ok(it, r["rerank"][rr], lookup)
            if (c != base_c) or (ct != base_cite):
                print(f"  {r['id']:<4} {rr:<13} correct {base_c}->{c}  cite {base_cite}->{ct} | {r['question'][:45]}")

    (DAY_DIR / "scoring_results.json").write_text(json.dumps(
        {"hit_rate": hit, "correct": correct, "cite": cite, "n": n,
         "hybrid_wins": hybrid_wins}, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'scoring_results.json'}")


if __name__ == "__main__":
    main()
