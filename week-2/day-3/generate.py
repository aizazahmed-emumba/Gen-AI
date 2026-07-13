"""
Week 2 - Day 3 (Course Day 8) - Answer generation with CITATIONS.

Retrieval quality is only worth measuring by what it does to the final answer.
So after we pick the top-5 context chunks, we ask the LLM to answer using ONLY
those chunks and to CITE the chunk numbers it used. That gives us two things to
score:
    * answer correctness  — did it get the fact right?
    * citation accuracy    — did it point at a chunk that actually supports it?
Reranking should improve both: cleaner top-5 -> the right fact is present AND the
model cites the chunk that truly contains it, instead of a plausible-looking
neighbour.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

DAY_DIR = Path(__file__).parent
CACHE_PATH = DAY_DIR / "gen_cache.json"
GEN_MODEL = "openai/gpt-oss-120b"

_cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}

SYSTEM = ("You answer strictly from the provided context passages. If the answer "
          "is not in the context, reply exactly: NOT IN CONTEXT. Keep the answer to "
          "1-2 sentences and cite the passage number(s) you used in square brackets, "
          "e.g. [2].")

PROMPT = """Question: {q}

Context passages:
{ctx}

Answer (cite passage numbers like [1]):"""


def generate_answer(question, context_chunks):
    """Return {answer, cited} where cited is the list of 1-based passage numbers used."""
    key = f"{question}::" + ",".join(c["id"] for c in context_chunks)
    if key in _cache:
        return _cache[key]

    ctx = "\n\n".join(f"[{i+1}] ({c['meta']['source']}) {c['doc'][:600]}"
                      for i, c in enumerate(context_chunks))
    answer = ask(PROMPT.format(q=question, ctx=ctx), model=GEN_MODEL,
                 temperature=0.0, system=SYSTEM).strip()
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)
                    if 1 <= int(n) <= len(context_chunks)})
    result = {"answer": answer, "cited": cited}
    _cache[key] = result
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=2))
    return result
