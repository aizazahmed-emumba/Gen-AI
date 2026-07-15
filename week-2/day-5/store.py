"""
store.py — the vector store, now backed by Qdrant (embedded, on-disk).

WHY QDRANT INSTEAD OF FAISS + meta.json:
  FAISS is a pure vector index — it has no notion of metadata, so we had to keep a
  parallel meta.json and filter in Python. Qdrant stores each vector together with
  a `payload` (its metadata) and applies filters NATIVELY inside the search. So:
    * one source of truth (no meta.json to keep in sync),
    * filtering happens in the engine (city/category/price as a query_filter),
    * the same code scales to millions of points without changing.

Local/embedded mode: `QdrantClient(path=...)` persists to disk with NO server.
Caveat (senior detail): a local Qdrant path is single-writer — only one process
may open it at a time. That's fine here (ingest runs offline, then the app opens
it), but you can't run ingest.py while the Streamlit app holds the store.
"""

import atexit

from qdrant_client import QdrantClient, models

import config
import embedder

_client = None


def _close():
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def load():
    global _client
    if _client is None:
        _client = QdrantClient(path=str(config.QDRANT_PATH))
        # Close explicitly at exit so the local store releases its lock cleanly,
        # instead of Qdrant's __del__ firing during interpreter teardown (noisy).
        atexit.register(_close)
    return _client


def _build_filter(where):
    """Translate {field: {allowed values}} into a native Qdrant filter.
    MatchAny = "field value is one of these" — matches our set semantics exactly."""
    if not where:
        return None
    must = [
        models.FieldCondition(key=field, match=models.MatchAny(any=sorted(vals)))
        for field, vals in where.items() if vals
    ]
    return models.Filter(must=must) if must else None


def search(query_text, where=None, k=config.TOP_K_SEMANTIC):
    """Semantic search + native metadata filter. Returns [{score, ...payload}]."""
    client = load()
    qv = embedder.embed_query(query_text)[0].tolist()
    result = client.query_points(
        config.COLLECTION,
        query=qv,
        query_filter=_build_filter(where),   # filtering happens INSIDE Qdrant
        limit=k,
        with_payload=True,
    ).points
    return [{"score": float(p.score), **p.payload} for p in result]


def all_urls():
    client = load()
    points, _ = client.scroll(config.COLLECTION, limit=10000, with_payload=True)
    return sorted({p.payload["url"] for p in points})
