"""
Week 2 - Day 2 (Course Day 7) - RUN the experiment.

For every question in the test set, run all five retrievers and save their top-5
chunks (text + metadata). No scoring here — score.py judges the saved output, so
we can re-score without re-querying.
"""

import json
from pathlib import Path

import ingest
import retrieve

DAY_DIR = Path(__file__).parent
TOP_K = 5


def main():
    test_set = json.loads((DAY_DIR / "test_set.json").read_text())
    collection = retrieve.get_collection()
    print(f"Collection has {collection.count()} chunks. Running {len(test_set)} questions...\n")

    results = []
    for item in test_set:
        q = item["question"]
        row = {"id": item["id"], "category": item["category"], "question": q, "retrieval": {}}
        for name, fn in retrieve.RETRIEVERS.items():
            hits = fn(collection, q, k=TOP_K)
            row["retrieval"][name] = [
                {"id": h["id"],
                 "source": h["meta"]["source"],
                 "section": h["meta"]["section"],
                 "page": h["meta"]["page"],
                 "doc": h["doc"]}
                for h in hits
            ]
        results.append(row)
        print(f"{item['id']:<4} [{item['category']:<11}] done")

    out = {"top_k": TOP_K, "results": results}
    (DAY_DIR / "run_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'run_results.json'}")


if __name__ == "__main__":
    main()
