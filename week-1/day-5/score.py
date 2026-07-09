import json
import re
from pathlib import Path

DAY5_DIR = Path(__file__).parent

REFUSAL_PATTERNS = [
    "not in document", "not in the document", "not stated", "not mentioned",
    "not specified", "no information", "does not state", "does not mention",
    "not given", "not provided", "cannot be determined", "no mention",
    "isn't stated", "is not stated", "not named", "no name",
]


def norm(t):
    return re.sub(r"\s+", " ", t.lower())


def refused(answer):
    return any(p in norm(answer) for p in REFUSAL_PATTERNS)


def correct(answer, item):
    if item["answerable"]:
        kts = item.get("key_terms") or []
        return any(norm(k) in norm(answer) for k in kts)
    # trap question: "correct" == correctly declining to answer
    return refused(answer)


def parse_pct(pos):
    m = re.search(r"(\d+)%", pos)
    return int(m.group(1)) if m else None


def classify(answer, item, strategy, fulltext_budget_pct):
    """Label each answer: correct / truncation / missed-info / hallucination."""
    if correct(answer, item):
        return "correct"
    if item["answerable"]:
        pos = parse_pct(item["doc_position"])
        if refused(answer):
            # a refusal on an answerable question = the model didn't have the fact
            if strategy == "fulltext" and pos is not None and pos > fulltext_budget_pct:
                return "truncation"   # fact was cut off before the model saw it
            return "missed-info"      # fact was available in principle but not surfaced/used
        # a confident, non-refusing, wrong answer = made something up
        return "hallucination"
    else:
        # trap question, and it did NOT refuse -> it invented an answer
        return "hallucination"


def main():
    results = json.loads((DAY5_DIR / "run_results.json").read_text(encoding="utf-8"))

    # what % of the document the full-text baseline actually saw (for truncation labeling)
    # 6000-token budget / ~27633-token doc ≈ 22%
    FULLTEXT_BUDGET_PCT = 22

    rows = []
    for r in results:
        rag_label = classify(r["rag_answer"], r, "rag", FULLTEXT_BUDGET_PCT)
        full_label = classify(r["fulltext_answer"], r, "fulltext", FULLTEXT_BUDGET_PCT)
        rows.append({
            "id": r["id"],
            "position": r["doc_position"],
            "rag_correct": rag_label == "correct",
            "rag_label": rag_label,
            "full_correct": full_label == "correct",
            "full_label": full_label,
        })

    n = len(rows)
    rag_ok = sum(r["rag_correct"] for r in rows)
    full_ok = sum(r["full_correct"] for r in rows)

    print(f"{'Q':<5}{'position':<20}{'RAG':<16}{'full-text'}")
    print("-" * 60)
    for r in rows:
        rag_s = "correct" if r["rag_correct"] else r["rag_label"]
        full_s = "correct" if r["full_correct"] else r["full_label"]
        print(f"{r['id']:<5}{r['position']:<20}{rag_s:<16}{full_s}")
    print("-" * 60)
    print(f"{'':<25}{f'{rag_ok}/{n}':<16}{f'{full_ok}/{n}'}")

    def tally(key):
        from collections import Counter
        return dict(Counter(r[key] for r in rows if r[key] != "correct"))

    print(f"\nRAG failure types:       {tally('rag_label')}")
    print(f"Full-text failure types: {tally('full_label')}")

    (DAY5_DIR / "scoring_results.json").write_text(
        json.dumps({"rows": rows, "rag_correct": rag_ok, "full_correct": full_ok, "n": n},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved scoring to {DAY5_DIR / 'scoring_results.json'}")


if __name__ == "__main__":
    main()
