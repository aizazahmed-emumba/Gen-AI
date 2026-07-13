"""
Week 2 - Day 3 (Course Day 8) - RERANKING: the second stage.

WHY TOP-K RETRIEVAL ALONE IS INSUFFICIENT
------------------------------------------
Stage-1 retrievers (vector, BM25) score each chunk in ISOLATION and cheaply, so
they can scan the whole corpus — but that cheapness is exactly their weakness:

  * Vector search uses a BI-ENCODER. The query is turned into a vector, each chunk
    was turned into a vector SEPARATELY (offline), and we compare the two vectors.
    The query and the chunk NEVER meet inside the model — so it can't notice that
    the chunk answers *this specific* question; it only knows they're "nearby" in
    a general topic sense. Great for recall, mediocre at putting the single best
    chunk at rank 1.
  * So the right chunk is usually IN the top-20, but often NOT at rank 1-5. Your
    Day-7 data proved it: HyDE found the Jonah chunk, then fusion pushed it out of
    the top-5. The information was retrieved and then lost to ranking. Feed those
    mis-ranked chunks to the LLM and it answers from the wrong context.

RERANKING fixes the ORDER. It re-scores the small stage-1 candidate set with a far
more accurate (and far more expensive) model, then keeps the top few. Two flavours:

  1. CROSS-ENCODER  (the industry standard)
     Feeds [query, chunk] through ONE transformer TOGETHER. Self-attention lets
     every query token look at every chunk token, so the model directly judges
     "does this chunk answer this query?" -> a single relevance score. Because it
     re-runs the model per (query, chunk) pair, it's too slow for the whole corpus
     — but perfect for re-scoring ~20 candidates. This is the bi-encoder/cross-
     encoder split: bi-encoder retrieves (fast, approximate), cross-encoder reranks
     (slow, precise). Two stages, each doing what it's good at.

  2. LLM-BASED reranking
     Hand the candidates to a general LLM and ask it to order them by relevance.
     More flexible (understands nuance, can follow task-specific instructions), but
     slower, costlier, and less consistent than a purpose-built cross-encoder.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

DAY_DIR = Path(__file__).parent
CACHE_PATH = DAY_DIR / "rerank_cache.json"
GEN_MODEL = "openai/gpt-oss-120b"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
_ce_model = None


# ─────────────────────────────────────────────────────────────────────────────
# 1) CROSS-ENCODER reranker (real model via sentence-transformers)
# ─────────────────────────────────────────────────────────────────────────────

def _get_cross_encoder():
    global _ce_model
    if _ce_model is None:
        from sentence_transformers import CrossEncoder      # lazy import (heavy)
        _ce_model = CrossEncoder(CROSS_ENCODER_MODEL)       # ~80MB, downloads once
    return _ce_model


def cross_encoder_rerank(query, candidates, k=5):
    model = _get_cross_encoder()
    pairs = [(query, c["doc"]) for c in candidates]
    scores = model.predict(pairs)                            # one relevance score per pair
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    return [candidates[i] for i in order[:k]]


# ─────────────────────────────────────────────────────────────────────────────
# 2) LLM-based reranker (Groq gpt-oss-120b)
# ─────────────────────────────────────────────────────────────────────────────

LLM_RERANK_PROMPT = """You are a search reranker. Given a question and {n} numbered passages, return the passage numbers ordered from MOST to LEAST relevant for answering the question. Return ONLY a comma-separated list of numbers, e.g. "3,1,5,2,4".

Question: {q}

Passages:
{passages}

Ranking:"""


def llm_rerank(query, candidates, k=5):
    key = f"{query}::" + ",".join(c["id"] for c in candidates)
    if key in _cache:
        order = _cache[key]
    else:
        passages = "\n".join(f"[{i+1}] {c['doc'][:500]}" for i, c in enumerate(candidates))
        raw = ask(LLM_RERANK_PROMPT.format(n=len(candidates), q=query, passages=passages),
                  model=GEN_MODEL, temperature=0.0)
        nums = [int(x) - 1 for x in __import__("re").findall(r"\d+", raw)]
        # keep valid, de-duplicated indices, then append any the LLM forgot
        seen, order = set(), []
        for i in nums:
            if 0 <= i < len(candidates) and i not in seen:
                seen.add(i); order.append(i)
        order += [i for i in range(len(candidates)) if i not in seen]
        _cache[key] = order
        CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=2))
    return [candidates[i] for i in order[:k]]


RERANKERS = {
    "cross_encoder": cross_encoder_rerank,
    "llm": llm_rerank,
}
