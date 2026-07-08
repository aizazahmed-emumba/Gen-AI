import json
import re
from pathlib import Path

DAY4_DIR = Path(__file__).parent

REFUSAL_PATTERNS = [
    "not in document", "not in the document", "not found", "not stated",
    "not specified", "no information", "not mentioned", "cannot be determined",
    "does not state", "does not specify", "does not mention", "not available",
    "not provided", "doesn't state", "doesn't specify", "doesn't mention",
    "not given", "unable to determine", "no mention", "i'm not aware",
    "i do not have", "i cannot verify", "unable to verify", "i'm unable to",
]

CITATION_RE = re.compile(r"\bpage\s+\d+\b|\bsource\s*:", re.IGNORECASE)


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text.lower())


def abstained(answer):
    lower = normalize_whitespace(answer)
    return any(p in lower for p in REFUSAL_PATTERNS)


def fact_match(answer, key_terms):
    if not key_terms:
        return None  # unanswerable questions don't have key_terms to match
    lower = normalize_whitespace(answer)
    return any(normalize_whitespace(term) in lower for term in key_terms)


def has_citation(answer):
    return bool(CITATION_RE.search(answer))


def score_answer(answer, item):
    if item["answerable"]:
        correct = fact_match(answer, item["key_terms"])
    else:
        correct = abstained(answer)  # "correct" for a trap question = correctly declining
    return {
        "correct": correct,
        "has_citation": has_citation(answer),
        "abstained": abstained(answer),
    }


def main():
    test_by_id = {t["id"]: t for t in json.loads((DAY4_DIR / "test_set.json").read_text(encoding="utf-8"))}
    results = json.loads((DAY4_DIR / "run_results.json").read_text(encoding="utf-8"))

    rows = []
    for r in results:
        item = test_by_id[r["id"]]
        llm_only_score = score_answer(r["llm_only_answer"], item)
        rag_score = score_answer(r["rag_answer"], item)
        rows.append({
            "id": r["id"],
            "question": r["question"],
            "answerable": item["answerable"],
            "llm_only_correct": llm_only_score["correct"],
            "llm_only_citation": llm_only_score["has_citation"],
            "rag_correct": rag_score["correct"],
            "rag_citation": rag_score["has_citation"],
        })

    n = len(rows)
    llm_only_correct_n = sum(1 for r in rows if r["llm_only_correct"])
    rag_correct_n = sum(1 for r in rows if r["rag_correct"])
    llm_only_citation_n = sum(1 for r in rows if r["llm_only_citation"])
    rag_citation_n = sum(1 for r in rows if r["rag_citation"])

    print(f"{'Metric':<30}{'LLM-only':<15}{'RAG'}")
    print("-" * 55)
    print(f"{'Answer correctness':<30}{f'{llm_only_correct_n}/{n}':<15}{f'{rag_correct_n}/{n}'}")
    print(f"{'Citation present':<30}{f'{llm_only_citation_n}/{n}':<15}{f'{rag_citation_n}/{n}'}")

    print("\nWhere RAG helped (LLM-only wrong, RAG right):")
    for r in rows:
        if not r["llm_only_correct"] and r["rag_correct"]:
            print(f"  [{r['id']}] {r['question']}")

    print("\nWhere RAG hurt (LLM-only right, RAG wrong):")
    for r in rows:
        if r["llm_only_correct"] and not r["rag_correct"]:
            print(f"  [{r['id']}] {r['question']}")

    print("\nBoth wrong:")
    for r in rows:
        if not r["llm_only_correct"] and not r["rag_correct"]:
            print(f"  [{r['id']}] {r['question']}")

    out_path = DAY4_DIR / "scoring_results.json"
    out_path.write_text(json.dumps({
        "rows": rows,
        "summary": {
            "n": n,
            "llm_only_correct": llm_only_correct_n,
            "rag_correct": rag_correct_n,
            "llm_only_citation": llm_only_citation_n,
            "rag_citation": rag_citation_n,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved scoring results to {out_path}")


if __name__ == "__main__":
    main()
