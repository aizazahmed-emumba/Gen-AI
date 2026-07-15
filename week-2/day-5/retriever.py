"""
retriever.py — the retrieval + reasoning pipeline (the "reasoning" the UI shows).

Steps, in order:
  1. FILTER   — turn preferences into hard metadata filters (city/category/price).
  2. SEARCH   — semantic search in FAISS within that filtered slice.
  3. RERANK   — a cross-encoder (the Day-8 winner) re-scores the candidates by
                TRUE query↔chunk relevance and keeps the top-k. Stage-1 vector
                search optimizes recall; the cross-encoder optimizes precision.
  4. JUDGE    — a lightweight Groq judge decides context_good / context_insufficient.
  5. RELAX    — if insufficient, drop a filter (category, then city) and retry.
                This is the "self-healing" step. NOTE: we only hard-filter on the
                RELIABLE fields (city, category); price_level is a noisy heuristic,
                so it's a soft rerank boost, not a filter — which is what stopped
                retrieval from relaxing on nearly every query.

Every step records a trace so the UI can display query → retrieval → reasoning.
"""

import json
import sys
from pathlib import Path

from sentence_transformers import CrossEncoder

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

import config
import store

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(config.RERANK_MODEL)
    return _reranker


PRICE_BONUS = 1.5   # soft nudge added to the rerank score when price_level matches


def _filters_from_prefs(prefs, relax=0):
    """Build the metadata filter from RELIABLE fields only.

    We HARD-filter on `city` and `category` because those are derived from the
    document's real structure (which article, which section) and are trustworthy.
    We deliberately do NOT filter on `price_level`: it is derived from a noisy
    keyword heuristic, so requiring it throws out relevant chunks that simply
    didn't say "cheap" — the main reason retrieval used to relax constantly.
    Price is applied softly in _rerank instead.

    `relax`: 0 = city+category, 1 = city only, 2 = no filter."""
    where = {}
    if relax < 2 and prefs.get("cities"):
        where["city"] = set(prefs["cities"])        # one OR several supported cities
    if relax < 1 and prefs.get("categories"):
        where["category"] = set(prefs["categories"])
    return where


def _rerank(query, hits, prefs, k=config.TOP_K_FINAL):
    """Cross-encoder relevance, plus a SOFT boost for chunks whose price_level
    matches the user's budget. Soft (a nudge, not a gate) so a mislabeled price
    can't exclude a relevant chunk — it just ranks slightly lower."""
    if not hits:
        return hits
    scores = _get_reranker().predict([(query, h["text"]) for h in hits])
    wanted = set(prefs.get("price_levels") or [])
    for h, s in zip(hits, scores):
        bonus = PRICE_BONUS if wanted and h.get("price_level") in wanted else 0.0
        h["rerank_score"] = float(s) + bonus
    return sorted(hits, key=lambda h: h["rerank_score"], reverse=True)[:k]


JUDGE_PROMPT = """You decide whether the retrieved passages are USABLE for answering a travel request. Be lenient: a helpful, grounded answer does NOT need to be comprehensive.

Reply "context_good" if the passages are on-topic (right city/theme) and contain relevant details that support at least a partial helpful answer.
Reply "context_insufficient" ONLY if the passages are essentially off-topic, about the wrong city, or contain no usable specifics.

Request: {query}

Passages:
{passages}

Reply JSON: {{"verdict": "context_good" or "context_insufficient", "reason": "<one sentence>"}}"""


def _judge(query, hits):
    if not hits:
        return {"verdict": "context_insufficient", "reason": "no passages retrieved"}
    passages = "\n\n".join(f"[{i+1}] ({h['city']}/{h['category']}/{h['price_level']}) {h['text'][:400]}"
                           for i, h in enumerate(hits))
    raw = ask(JUDGE_PROMPT.format(query=query, passages=passages),
              model=config.GROQ_MODEL, temperature=0.0,
              response_format={"type": "json_object"})
    try:
        obj = json.loads(raw)
        verdict = obj.get("verdict")
        if verdict not in ("context_good", "context_insufficient"):
            verdict = "context_insufficient"
        return {"verdict": verdict, "reason": obj.get("reason", "")}
    except json.JSONDecodeError:
        return {"verdict": "context_insufficient", "reason": "judge returned invalid JSON"}


def retrieve(query, prefs):
    """Full pipeline with one relax-and-retry. Returns (hits, trace)."""
    trace = {"attempts": []}
    for relax in (0, 1, 2):
        where = _filters_from_prefs(prefs, relax)
        raw_hits = store.search(query, where=where, k=config.TOP_K_SEMANTIC)
        hits = _rerank(query, raw_hits, prefs)
        judged = _judge(query, hits)
        trace["attempts"].append({
            "relax_level": relax,
            "filters": {k: sorted(v) for k, v in where.items()},
            "n_candidates": len(raw_hits),
            "verdict": judged["verdict"],
            "reason": judged["reason"],
        })
        if judged["verdict"] == "context_good" or not raw_hits:
            trace["final_relax_level"] = relax
            trace["verdict"] = judged["verdict"]
            return hits, trace
        # else: insufficient -> relax and retry (assignment: retry once, we allow up to 2 backoffs)
    trace["final_relax_level"] = 2
    trace["verdict"] = judged["verdict"]
    return hits, trace
