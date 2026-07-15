"""
embedder.py — wraps the embedding model (BAAI/bge-small-en-v1.5).

WHY THIS MODEL (the justification the assignment asks for):
  * Strong MTEB retrieval score for its size — punches well above 384 dimensions.
  * 384-dim → a small, fast FAISS index and low memory (matters for a local app).
  * Runs IN-PROCESS via sentence-transformers, so the app needs no extra server
    (unlike an Ollama-hosted model) — one fewer moving part to deploy/demo.
  * Apache-2.0 licensed.

TWO THINGS THAT ARE EASY TO GET WRONG:

1. ASYMMETRIC EMBEDDING. bge is trained so that a QUERY and the DOCUMENT that
   answers it land near each other — but only if you prepend the query with the
   instruction it was trained on. Documents are embedded as-is. Forget the prefix
   and query/doc vectors drift apart and recall drops. So we expose two methods:
   embed_query() (adds the prefix) and embed_documents() (no prefix).

2. NORMALIZATION. We L2-normalize every vector. Then cosine similarity == inner
   product, so we can use FAISS's fast IndexFlatIP and read the scores as cosine.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

import config

# bge-v1.5 English retrieval instruction — prepended to QUERIES ONLY.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


def embed_documents(texts):
    """Embed corpus chunks (no prefix). Returns float32 [n, dim], L2-normalized."""
    vecs = _get_model().encode(texts, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
    return vecs.astype("float32")


def embed_query(text):
    """Embed a single user query (WITH the retrieval prefix). Returns [1, dim]."""
    vec = _get_model().encode([QUERY_PREFIX + text], normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=False)
    return vec.astype("float32")


def dim():
    return _get_model().get_sentence_embedding_dimension()
