"""
Week 2 - Day 4 (Course Day 9) - Fixed retrieval context.

Day 9 is about GENERATION, so we freeze retrieval: every prompt gets the SAME
top-5 passages for a question. That isolation is the point — any difference in
answer quality is caused by the PROMPT / output format, not by different context.

We reuse Day-8's weighted-hybrid retriever (the tuned one) and cache the contexts
to contexts.json so both prompts and every re-run see byte-identical passages.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "day-3"))
import retrieve  # Day-8 retrievers over the Day-7 collection

DAY_DIR = Path(__file__).parent
CONTEXTS = DAY_DIR / "contexts.json"
K = 5


def build_contexts():
    if CONTEXTS.exists():
        return json.loads(CONTEXTS.read_text())
    retrieve.load()
    test = json.loads((DAY_DIR.parent / "day-3" / "test_set.json").read_text())
    out = {}
    for item in test:
        hits = retrieve.hybrid_weighted(item["question"], k=K)
        out[item["id"]] = [
            {"n": i + 1, "id": h["id"], "source": h["meta"]["source"],
             "section": h["meta"]["section"], "text": h["doc"][:600]}
            for i, h in enumerate(hits)
        ]
    CONTEXTS.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def format_passages(passages):
    """Render the passages the way both prompts will show them to the model."""
    return "\n\n".join(f"[{p['n']}] ({p['source']}) {p['text']}" for p in passages)


if __name__ == "__main__":
    ctx = build_contexts()
    print(f"Built contexts for {len(ctx)} questions -> {CONTEXTS}")
