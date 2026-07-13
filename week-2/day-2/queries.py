"""
Week 2 - Day 2 (Course Day 7) - QUERY OPTIMIZATION techniques.

The retriever from Day 5 did the naive thing: embed the user's raw question, find
the nearest chunks. That fails in three recurring ways, and each technique here
fixes one of them.

    Problem                                        Fix
    -------                                        ---
    A question is phrased NOTHING like its answer  -> HyDE
    One phrasing is one narrow probe into space    -> multi-query rewriting
    A compound question is two facts averaged into
      one blurry vector that matches neither       -> sub-query decomposition

All three use an LLM (Groq llama-3.3-70b) to TRANSFORM THE QUERY before it ever
touches the vector DB. The chunks/embeddings never change — only what we search
WITH changes. That is the whole mental model of "query optimization": fix the
query side, not the index side.

We cache every LLM output to disk (llm_cache.json) so re-running the experiment
is free and deterministic and doesn't burn the Groq daily token budget.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

DAY_DIR = Path(__file__).parent
CACHE_PATH = DAY_DIR / "llm_cache.json"
LLM_MODEL = "llama-3.3-70b-versatile"

_cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def _cached(key, produce):
    """Memoize LLM calls on disk. Key = technique + question, value = LLM output."""
    if key in _cache:
        return _cache[key]
    value = produce()
    _cache[key] = value
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=2))
    return value


# ─────────────────────────────────────────────────────────────────────────────
# HyDE — Hypothetical Document Embeddings
# ─────────────────────────────────────────────────────────────────────────────
# THE PROBLEM: an embedding model places text by MEANING, but a *question* and its
# *answer* are written very differently. "What is least privilege?" is short and
# interrogative; the answer chunk is a long declarative control description. Their
# embeddings can sit surprisingly far apart, so the true answer ranks low.
#
# THE TRICK: don't search with the question. Ask the LLM to HALLUCINATE a short
# answer — a fake passage that *looks like the kind of document that would contain
# the answer* — and search with THAT. A fake answer is phrased like a real answer,
# so its embedding lands in the right neighbourhood, pulling up the real chunk.
#
# THE RISK (your Day-1 finding!): if the LLM invents WRONG facts, the fake passage
# points at the wrong neighbourhood and HyDE actively hurts. A weak 3B model
# tanked your score 83->67. A 70B model hallucinates more plausibly, so it should
# behave better here — we will measure whether that's true.

HYDE_PROMPT = """Write a short, factual passage (2-4 sentences) that directly answers the question below, as if it were an excerpt from a reference document or novel. Do not hedge, do not say "I don't know" — just write the passage as if the answer is known.

Question: {q}

Passage:"""


def hyde(question):
    def produce():
        return ask(HYDE_PROMPT.format(q=question), model=LLM_MODEL, temperature=0.3).strip()
    passage = _cached(f"hyde::{question}", produce)
    # We search with the hypothetical passage. Appending the original question keeps
    # a little of the user's own signal so a bad hallucination can't fully derail it.
    return f"{passage}\n\n{question}"


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-QUERY rewriting / expansion
# ─────────────────────────────────────────────────────────────────────────────
# THE PROBLEM: your one phrasing is a single dart thrown at embedding space. The
# answer chunk might use words you didn't ("harpooneer" vs "whale hunter",
# "device lock" vs "screen lock"). If your dart lands just past it, you miss.
#
# THE TRICK: ask the LLM for N alternative phrasings that mean the same thing but
# use different vocabulary and angles. Throw all N darts, retrieve for each, then
# MERGE the hit-lists. Any chunk that several phrasings agree on rises to the top.
# This buys RECALL (you find more true answers) at the cost of some precision
# (a wider net also drags in more noise).

MULTIQUERY_PROMPT = """Generate {n} different search queries that all seek the same answer as the question below. Vary the wording, synonyms, and phrasing so together they cover more ways the answer might be written. Return ONLY the queries, one per line, no numbering.

Question: {q}"""


def multi_query(question, n=3):
    def produce():
        raw = ask(MULTIQUERY_PROMPT.format(q=question, n=n), model=LLM_MODEL, temperature=0.7)
        lines = [ln.strip(" -0123456789.").strip() for ln in raw.splitlines() if ln.strip()]
        return [ln for ln in lines if ln][:n]
    variants = _cached(f"multiquery::{n}::{question}", produce)
    return [question] + variants          # always keep the original phrasing too


# ─────────────────────────────────────────────────────────────────────────────
# SUB-QUERY decomposition
# ─────────────────────────────────────────────────────────────────────────────
# THE PROBLEM: "Who narrates Moby-Dick, AND what does least privilege require?" is
# TWO unrelated facts. Embed it as one string and you get the AVERAGE of a novel
# vector and a security-standard vector — a mush that's near neither answer. This
# is the exact "blurred vector" failure you documented in Week-2-Day-1, but on the
# query side instead of the chunk side.
#
# THE TRICK: ask the LLM to split the question into independent sub-questions.
# Retrieve for each separately (each gets a clean, focused vector — and can even
# get its OWN metadata filter, since the two halves may live in different sources),
# then union the results. Simple questions are returned unchanged (no over-split).

DECOMPOSE_PROMPT = """Break the question into the minimal set of independent, self-contained sub-questions needed to answer it. If it already asks only ONE thing, return it unchanged as a single line. Return ONLY the sub-questions, one per line, no numbering.

Question: {q}"""


def sub_queries(question):
    def produce():
        raw = ask(DECOMPOSE_PROMPT.format(q=question), model=LLM_MODEL, temperature=0.2)
        lines = [ln.strip(" -0123456789.").strip() for ln in raw.splitlines() if ln.strip()]
        return [ln for ln in lines if ln] or [question]
    return _cached(f"subq::{question}", produce)


# ─────────────────────────────────────────────────────────────────────────────
# METADATA ROUTER  (query understanding -> a filter)
# ─────────────────────────────────────────────────────────────────────────────
# This is the query-time half of "metadata-aware retrieval". A filter is only
# useful if the system can DECIDE, from the question alone, which filter to apply.
# In production that decision is made by a small "router" / "query understanding"
# step. Here the LLM classifies the question into a doc_type, which becomes a hard
# metadata pre-filter (only fiction chunks, or only standard chunks, get to
# compete in the vector search).
#
# THE UPSIDE: removes entire wrong sources before ranking -> less noise, higher
# precision. THE DANGER: a filter is a CLIFF, not a nudge — route wrong and the
# real answer is excluded outright, no ranking can save it. That asymmetry is the
# key lesson about filters, and we'll see it bite the cross-source compound Q17.

ROUTER_PROMPT = """You route a question to the right document collection.
Collections:
- "fiction": novels (The Metamorphosis by Kafka; Moby-Dick by Melville).
- "standard": the NIST SP 800-53 security & privacy controls catalog.
Answer with EXACTLY one word: fiction, standard, or both (use "both" only if the question genuinely needs both).

Question: {q}
Answer:"""


def route_doc_type(question):
    def produce():
        out = ask(ROUTER_PROMPT.format(q=question), model=LLM_MODEL, temperature=0.0).strip().lower()
        for choice in ("both", "fiction", "standard"):
            if choice in out:
                return choice
        return "both"
    choice = _cached(f"router::{question}", produce)
    if choice == "both":
        return None                        # None => no filter, search everything
    return {"doc_type": choice}            # a Chroma `where` clause


if __name__ == "__main__":
    # quick smoke test of each technique on one example
    q = "Who is the narrator of Moby-Dick, and what does least privilege require?"
    print("HyDE:\n", hyde(q), "\n")
    print("MULTI-QUERY:\n", multi_query(q), "\n")
    print("SUB-QUERIES:\n", sub_queries(q), "\n")
    print("ROUTE:\n", route_doc_type(q))
