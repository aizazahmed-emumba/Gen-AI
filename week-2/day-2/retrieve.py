"""
Week 2 - Day 2 (Course Day 7) - RETRIEVAL: baseline vs optimized.

Same collection, same embeddings for every strategy — the ONLY thing that changes
is (a) what query text(s) we search with and (b) whether we apply a metadata
filter. That isolation is deliberate: any score difference is attributable to
query optimization + filtering, nothing else.

We expose several retrievers so we can ATTRIBUTE gains, not just see a final
number:
    baseline    raw question, no filter                (the Day-5 method)
    multiquery  query expansion, no filter              (recall lever)
    hyde        hypothetical-answer embedding, no filter (phrasing-gap lever)
    filtered    raw question + routed metadata filter   (precision lever)
    optimized   THE WORKS: decompose -> per-sub filter -> multiquery+hyde -> fuse

MERGING many hit-lists: Reciprocal Rank Fusion (RRF). Each retrieved chunk scores
sum(1/(k+rank)) across every query that returned it. A chunk several queries rank
highly floats up; a chunk only one query liked stays low. RRF needs no tuning and
ignores the raw distance scales (which differ per query), so it's the standard way
to fuse multi-query / hybrid results.
"""

from pathlib import Path

import chromadb

from queries import hyde, multi_query, sub_queries, route_doc_type
import ingest  # reuse the embedding function + collection name

DAY_DIR = Path(__file__).parent
RRF_K = 60  # standard RRF constant; larger => flatter, less top-heavy fusion


def get_collection():
    client = chromadb.PersistentClient(path=str(ingest.CHROMA_DIR))
    return client.get_collection(
        ingest.COLLECTION,
        embedding_function=ingest.OllamaEmbeddingFunction(),
    )


def _query(collection, query_texts, k, where=None):
    """Run one or more query texts; return per-query ranked lists of hits."""
    res = collection.query(query_texts=query_texts, n_results=k, where=where)
    per_query = []
    for i in range(len(query_texts)):
        hits = [
            {"id": res["ids"][i][j],
             "doc": res["documents"][i][j],
             "meta": res["metadatas"][i][j],
             "distance": res["distances"][i][j]}
            for j in range(len(res["ids"][i]))
        ]
        per_query.append(hits)
    return per_query


def _rrf_fuse(per_query_lists, k):
    """Reciprocal Rank Fusion across several ranked lists -> single top-k list."""
    scores, seen = {}, {}
    for hits in per_query_lists:
        for rank, h in enumerate(hits):
            scores[h["id"]] = scores.get(h["id"], 0.0) + 1.0 / (RRF_K + rank)
            seen[h["id"]] = h
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [seen[i] for i in ordered[:k]]


# ─────────────────────────────────────────────────────────────────────────────
# The retrievers
# ─────────────────────────────────────────────────────────────────────────────

def retrieve_baseline(collection, question, k=5):
    return _query(collection, [question], k)[0]


def retrieve_multiquery(collection, question, k=5):
    variants = multi_query(question)                 # original + paraphrases
    return _rrf_fuse(_query(collection, variants, k), k)


def retrieve_hyde(collection, question, k=5):
    return _query(collection, [hyde(question)], k)[0]


def retrieve_filtered(collection, question, k=5):
    where = route_doc_type(question)                 # None => no filter
    return _query(collection, [question], k, where=where)[0]


def retrieve_optimized(collection, question, k=5):
    """Full pipeline. Decompose first so each fact gets its OWN focused retrieval
    and its OWN metadata filter — the compound-question fix — then expand each
    sub-query with multi-query + HyDE, and RRF-fuse everything into one top-k."""
    all_lists = []
    for sub in sub_queries(question):
        where = route_doc_type(sub)                  # per-sub filter (key for cross-source Qs)
        texts = multi_query(sub) + [hyde(sub)]       # expansion: paraphrases + hypothetical answer
        all_lists.extend(_query(collection, texts, k, where=where))
    return _rrf_fuse(all_lists, k)


RETRIEVERS = {
    "baseline": retrieve_baseline,
    "multiquery": retrieve_multiquery,
    "hyde": retrieve_hyde,
    "filtered": retrieve_filtered,
    "optimized": retrieve_optimized,
}
