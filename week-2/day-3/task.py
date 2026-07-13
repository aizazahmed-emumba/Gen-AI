"""
Week 2 - Day 3 (Course Day 8) - RUN the experiment.

Two independent measurements per question:

  (A) RETRIEVAL hit-rate@5 — vector vs bm25 vs hybrid. Retrieval only, no LLM.

  (B) RERANKING effect — fix hybrid as the stage-1 retriever, take its top-15 as a
      candidate POOL, then compare three ways of choosing the final top-5 that the
      LLM answers from:
          none          hybrid's own top-5 (no reranking)
          cross_encoder ms-marco cross-encoder re-sorts the pool -> top-5
          llm           gpt-oss-120b re-sorts the pool -> top-5
      For each we generate an answer with citations, so we can score correctness
      and citation accuracy before vs after reranking.

Only chunk IDs + generated answers are saved; score.py rehydrates chunk text from
the collection, so the ground truth for scoring lives in one place.
"""

import json
from pathlib import Path

import retrieve
import rerank
import generate

DAY_DIR = Path(__file__).parent
POOL = 15   # stage-1 candidates handed to the reranker
K = 5


def ids(hits):
    return [h["id"] for h in hits]


def main():
    test_set = json.loads((DAY_DIR / "test_set.json").read_text())
    retrieve.load()
    print(f"Running {len(test_set)} questions...\n")

    results = []
    for item in test_set:
        q = item["question"]
        row = {"id": item["id"], "category": item["category"], "question": q}

        # (A) retrieval hit-rate: top-5 from each retriever
        row["retrieval"] = {name: ids(fn(q, k=K)) for name, fn in retrieve.RETRIEVERS.items()}

        # (B) reranking: hybrid top-15 pool -> three top-5 selections -> generate
        pool = retrieve.hybrid_search(q, k=POOL)
        variants = {
            "none": pool[:K],
            "cross_encoder": rerank.cross_encoder_rerank(q, pool, k=K),
            "llm": rerank.llm_rerank(q, pool, k=K),
        }
        row["rerank"] = {}
        for name, top5 in variants.items():
            gen = generate.generate_answer(q, top5)
            row["rerank"][name] = {"top5": ids(top5), "answer": gen["answer"], "cited": gen["cited"]}

        results.append(row)
        print(f"{item['id']:<4} [{item['category']:<11}] "
              f"answers: none/ce/llm done")

    (DAY_DIR / "run_results.json").write_text(
        json.dumps({"pool": POOL, "k": K, "results": results}, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'run_results.json'}")


if __name__ == "__main__":
    main()
