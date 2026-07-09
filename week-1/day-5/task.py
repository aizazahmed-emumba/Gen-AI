"""
Day 5 — Basic RAG with Chroma DB, compared against full-text (no-retrieval) answering.

Pipeline taught here:  ingest -> embed -> store (Chroma) -> retrieve -> answer.

Everything runs LOCALLY and open-source:
  - embeddings : mxbai-embed-large   (via Ollama)
  - vector DB  : Chroma               (persistent, on disk)
  - answer LLM : llama3.2:3b          (via Ollama)
No cloud APIs, no rate limits.
"""

import sys
import json
from pathlib import Path

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import ollama
import tiktoken

DAY5_DIR = Path(__file__).parent
DOC_PATH = DAY5_DIR / "docs" / "metamorphosis.txt"
CHROMA_DIR = DAY5_DIR / "chroma_db"

EMBED_MODEL = "mxbai-embed-large"
ANSWER_MODEL = "llama3.2:3b"

CHUNK_WORDS = 150      # simple fixed-size word chunking, no overlap, no advanced strategy
TOP_K = 4              # how many chunks Chroma returns per question for RAG

# The full-text baseline can't hold the whole ~27k-token document — small/cheap
# models have limited context. We simulate a modest budget: only the first
# ~6000 tokens of the document get passed. Everything after that is TRUNCATED
# away, which is exactly the failure mode we want to observe (facts late in the
# document become invisible to the baseline).
FULLTEXT_BUDGET_TOKENS = 6000

ENC = tiktoken.get_encoding("cl100k_base")


# ─── Ingest: load the document and split into fixed-size word chunks ─────────

def load_document():
    return DOC_PATH.read_text(encoding="utf-8")


def chunk_by_words(text, size=CHUNK_WORDS):
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


# ─── Embed: a Chroma embedding function backed by a local Ollama model ───────
# This teaches the key idea that a vector DB is EMBEDDING-AGNOSTIC: Chroma just
# stores whatever vectors you hand it and does fast similarity search over them.
# Chroma also ships a zero-config default embedder (all-MiniLM-L6-v2); we plug
# in our stronger mxbai model instead to show the seam is swappable.

class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model=EMBED_MODEL):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            resp = ollama.embed(model=self.model, input=text, options={"num_ctx": 8192})
            vectors.append(resp["embeddings"][0])
        return vectors

    def name(self):
        return f"ollama-{self.model}"


# ─── Store: build (or rebuild) the Chroma collection ─────────────────────────

def build_collection(chunks):
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Start clean each run so re-runs are reproducible.
    try:
        client.delete_collection("metamorphosis")
    except Exception:
        pass
    collection = client.create_collection(
        "metamorphosis",
        embedding_function=OllamaEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},  # use cosine similarity (same measure as Day 4)
    )
    # Chroma embeds each document with our embedding function and stores it.
    collection.add(
        ids=[f"chunk-{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[{"chunk_index": i} for i in range(len(chunks))],
    )
    return collection


# ─── Answer: two strategies ──────────────────────────────────────────────────

ANSWER_INSTRUCTION = (
    'Answer the question using ONLY the context provided. Be concise. '
    'If the answer is not in the context, reply exactly: "NOT IN DOCUMENT". '
    "Do not use outside knowledge."
)


def ask_llm(prompt, num_ctx):
    resp = ollama.chat(
        model=ANSWER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0, "num_ctx": num_ctx},
    )
    return resp["message"]["content"].strip()


def rag_answer(question, collection, k=TOP_K):
    result = collection.query(query_texts=[question], n_results=k)
    chunks = result["documents"][0]
    ids = result["ids"][0]
    context = "\n\n".join(f"[{cid}] {c}" for cid, c in zip(ids, chunks))
    prompt = f"{ANSWER_INSTRUCTION}\n\nCONTEXT:\n{context}\n\nQUESTION: {question}"
    return ask_llm(prompt, num_ctx=4096), ids


def truncate_to_tokens(text, budget):
    tokens = ENC.encode(text)
    if len(tokens) <= budget:
        return text, False
    return ENC.decode(tokens[:budget]), True


def fulltext_answer(question, full_text):
    context, truncated = truncate_to_tokens(full_text, FULLTEXT_BUDGET_TOKENS)
    prompt = f"{ANSWER_INSTRUCTION}\n\nDOCUMENT:\n{context}\n\nQUESTION: {question}"
    return ask_llm(prompt, num_ctx=8192), truncated


def main():
    print("Loading document...")
    text = load_document()
    doc_tokens = len(ENC.encode(text))
    chunks = chunk_by_words(text)
    print(f"Document: {len(text.split())} words / {doc_tokens} tokens -> {len(chunks)} chunks of {CHUNK_WORDS} words.")
    print(f"Full-text baseline budget: {FULLTEXT_BUDGET_TOKENS} tokens "
          f"({FULLTEXT_BUDGET_TOKENS / doc_tokens:.0%} of the document fits; the rest is truncated).")

    print("\nBuilding Chroma collection (ingest -> embed -> store)...")
    collection = build_collection(chunks)
    print(f"Stored {collection.count()} chunks in Chroma at {CHROMA_DIR}")

    test_set = json.loads((DAY5_DIR / "test_set.json").read_text(encoding="utf-8"))

    results = []
    for item in test_set:
        qid, question = item["id"], item["question"]
        print(f"\n{'=' * 70}\n[{qid}] {question}  ({item['doc_position']})")

        rag, retrieved_ids = rag_answer(question, collection)
        print(f"  retrieved: {retrieved_ids}")
        print(f"  [RAG]:        {rag[:150]}")

        full, was_truncated = fulltext_answer(question, text)
        print(f"  [full-text]:  {full[:150]}  (truncated={was_truncated})")

        results.append({
            "id": qid,
            "question": question,
            "doc_position": item["doc_position"],
            "answerable": item["answerable"],
            "expected_answer": item["expected_answer"],
            "key_terms": item.get("key_terms"),
            "retrieved_ids": retrieved_ids,
            "rag_answer": rag,
            "fulltext_answer": full,
            "fulltext_truncated": was_truncated,
        })

    out_path = DAY5_DIR / "run_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved raw run results to {out_path}")


if __name__ == "__main__":
    main()
