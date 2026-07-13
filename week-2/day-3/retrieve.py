"""
Week 2 - Day 3 (Course Day 8) - Retrieval strategies: vector, BM25, hybrid.

Reuses the Day-7 Chroma collection (892 chunks, mxbai-embed-large) unchanged — the
index is identical, only the RETRIEVAL METHOD varies, so any difference is
attributable to the method, nothing else.

    vector  -> nearest neighbours by embedding cosine   (matches MEANING)
    bm25    -> Okapi BM25 over the same chunks           (matches WORDS)
    hybrid  -> RRF fusion of the two ranked lists        (best of both)

Why fuse with RRF and not by adding scores? Vector cosine distances (~0.2-0.4) and
BM25 scores (0..20+) live on totally different scales — summing them lets BM25
dominate arbitrarily. RRF throws away the raw scores and keeps only RANK, so the
two retrievers vote as equals: a chunk both rank highly wins.
"""

import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).parent.parent / "day-2"))
import ingest  # Day-7 embedding function + collection location

from bm25 import BM25

RRF_K = 60

_STATE = {}


def load():
    """Open the Day-7 collection once and build the BM25 index over its chunks."""
    if _STATE:
        return _STATE
    client = chromadb.PersistentClient(path=str(ingest.CHROMA_DIR))
    col = client.get_collection(ingest.COLLECTION, embedding_function=ingest.OllamaEmbeddingFunction())
    dump = col.get(limit=col.count(), include=["documents", "metadatas"])
    lookup = {i: {"doc": d, "meta": m}
              for i, d, m in zip(dump["ids"], dump["documents"], dump["metadatas"])}
    _STATE.update(col=col, lookup=lookup,
                  bm25=BM25(dump["ids"], dump["documents"]))
    return _STATE


def _hit(cid):
    e = _STATE["lookup"][cid]
    return {"id": cid, "doc": e["doc"], "meta": e["meta"]}


# ─────────────────────────────────────────────────────────────────────────────
# The three retrievers — each returns a ranked list of hit dicts
# ─────────────────────────────────────────────────────────────────────────────

def vector_search(query, k=20):
    s = load()
    res = s["col"].query(query_texts=[query], n_results=k)
    return [{"id": res["ids"][0][j], "doc": res["documents"][0][j], "meta": res["metadatas"][0][j]}
            for j in range(len(res["ids"][0]))]


def bm25_search(query, k=20):
    s = load()
    return [_hit(cid) for cid, _score in s["bm25"].search(query, k=k)]


def _fuse(vec, lex, k, w_vec=1.0, w_lex=1.0):
    """Weighted Reciprocal Rank Fusion of the vector and BM25 rankings."""
    scores = {}
    for ranked, w in ((vec, w_vec), (lex, w_lex)):
        for rank, h in enumerate(ranked):
            scores[h["id"]] = scores.get(h["id"], 0.0) + w / (RRF_K + rank)
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [_hit(cid) for cid in ordered[:k]]


def hybrid_search(query, k=20):
    """Naive equal-weight hybrid: vector and BM25 vote as equals."""
    return _fuse(vector_search(query, k=k), bm25_search(query, k=k), k)


def hybrid_weighted(query, k=20, w_lex=0.4):
    """Vector-weighted hybrid: trust the stronger retriever (vector) more, and let
    BM25 only *rescue* cases vector missed (exact-term / rare-token queries). w_lex
    < 1 stops BM25's confident-but-wrong hits from demoting vector's correct ones."""
    return _fuse(vector_search(query, k=k), bm25_search(query, k=k), k, w_vec=1.0, w_lex=w_lex)


RETRIEVERS = {
    "vector": vector_search,
    "bm25": bm25_search,
    "hybrid": hybrid_search,
    "hybrid_weighted": hybrid_weighted,
}
