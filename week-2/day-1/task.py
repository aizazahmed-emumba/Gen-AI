"""
Week 2 - Day 1 - Chunking strategies and their impact on retrieval quality.

Same corpus, same embedder, same questions, same vector DB.
The ONLY thing that changes is HOW we cut the document into chunks:

  1. fixed        - 150 words, no overlap            (arbitrary cuts)          <- Day-5 baseline
  2. overlapping  - 150 words, 30-word overlap        (arbitrary cuts + overlap)
  3. recursive    - split on natural boundaries        (paragraph -> sentence -> word)

We then measure RETRIEVAL quality only (no LLM answering here): for each
question, does the chunk that actually contains the answer show up in the
top-5 retrieved chunks?  -> hit-rate@5.

Everything is local / open-source via Ollama (mxbai-embed-large + Chroma).
"""

import json
import re
from pathlib import Path

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import ollama

DAY_DIR = Path(__file__).parent
DOC_PATH = DAY_DIR / "docs" / "metamorphosis.txt"
CHROMA_DIR = DAY_DIR / "chroma_db"

EMBED_MODEL = "mxbai-embed-large"   # identical to Day 5, so the only variable is chunking

CHUNK_WORDS = 150       # fixed & overlapping target size (words)
OVERLAP_WORDS = 30      # overlapping strategy: 20% of the window is shared with the previous chunk
RECURSIVE_CHARS = 1050  # recursive target size, tuned so recursive chunks average
                        # ~149 words - the SAME as the fixed strategy. This is
                        # deliberate: it holds chunk size constant so the only
                        # difference between fixed and recursive is WHERE the cuts
                        # fall (arbitrary vs. natural boundaries), not how big the
                        # chunks are.
TOP_K = 10              # retrieve 10 so we can see rank even when a chunk misses the top-5


# ─────────────────────────────────────────────────────────────────────────────
# 1) THE THREE CHUNKING STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def chunk_fixed(text, size=CHUNK_WORDS):
    """Cut every `size` words, no overlap. Boundaries fall wherever they fall -
    often mid-sentence. This is the Day-5 baseline."""
    words = text.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def chunk_overlapping(text, size=CHUNK_WORDS, overlap=OVERLAP_WORDS):
    """Same arbitrary word cuts, but each chunk repeats the last `overlap` words
    of the previous one. A fact sitting on a boundary now appears WHOLE in at
    least one chunk instead of being sliced in two. The step between chunk
    starts is (size - overlap)."""
    words = text.split()
    step = size - overlap
    chunks = []
    for i in range(0, len(words), step):
        chunk = words[i:i + size]
        if chunk:
            chunks.append(" ".join(chunk))
        if i + size >= len(words):
            break
    return chunks


# Separators in priority order: paragraph -> line -> sentence -> word.
# The recursive splitter always tries the BIGGEST natural unit first and only
# drops to a finer one when a piece is still too large.
RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", " "]


def _merge_tiny(chunks, min_words=20):
    """Boundary splitting can leave junk fragments - e.g. the lone chapter
    markers "I" / "II" / "III" become 1-word chunks. A 1-word chunk embeds to
    noise and wastes a retrieval slot, so fold any sub-`min_words` fragment into
    a neighbour (previous if there is one, otherwise the next)."""
    out = []
    for c in chunks:
        if out and len(c.split()) < min_words:
            out[-1] += "\n" + c
        else:
            out.append(c)
    if len(out) >= 2 and len(out[0].split()) < min_words:
        out[1] = out[0] + "\n" + out[1]
        out = out[1:]
    return out


def chunk_recursive(text, target=RECURSIVE_CHARS, separators=RECURSIVE_SEPARATORS):
    """Boundary-aware ("recursive") chunking.

    Idea: never cut in the middle of a sentence if a paragraph break is
    available; never cut mid-word if a sentence break is available. We do this
    by splitting on the highest-priority separator that occurs in the text, then
    greedily merging the pieces back up to `target` size. Any single piece that
    is still too big is recursively split on the NEXT-finer separator.

    Result: chunks that end on natural boundaries, so each chunk is a coherent
    unit of meaning - which is what the embedding model was trained to encode.
    """
    return _merge_tiny(_recursive_split(text, target, separators))


def _recursive_split(text, target, separators):
    text = text.strip()
    if len(text) <= target:
        return [text] if text else []

    # pick the first separator that actually appears in this text
    sep, rest = "", []
    for i, s in enumerate(separators):
        if s in text:
            sep, rest = s, separators[i + 1:]
            break
    if sep == "":
        # no separator left -> hard character split (last resort)
        return [text[i:i + target] for i in range(0, len(text), target)]

    pieces = text.split(sep)
    chunks, buf = [], ""
    for piece in pieces:
        piece = piece + sep
        if len(piece) > target:
            # this single piece won't fit even alone -> recurse on a finer separator
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_recursive_split(piece, target, rest))
        elif len(buf) + len(piece) <= target:
            buf += piece                      # keep packing into the current chunk
        else:
            chunks.append(buf.strip())        # current chunk is full; start a new one
            buf = piece
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


STRATEGIES = {
    "fixed": chunk_fixed,
    "overlapping": chunk_overlapping,
    "recursive": chunk_recursive,
}


# ─────────────────────────────────────────────────────────────────────────────
# 2) EMBED + STORE  (identical embedder for every strategy)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model=EMBED_MODEL):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        out = []
        for text in input:
            resp = ollama.embed(model=self.model, input=text, options={"num_ctx": 8192})
            out.append(resp["embeddings"][0])
        return out

    def name(self):
        return f"ollama-{self.model}"


def build_collection(client, name, chunks):
    try:
        client.delete_collection(name)
    except Exception:
        pass
    collection = client.create_collection(
        name,
        embedding_function=OllamaEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=[f"{name}-{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[{"chunk_index": i} for i in range(len(chunks))],
    )
    return collection


# ─────────────────────────────────────────────────────────────────────────────
# 3) RETRIEVE + SAVE
# ─────────────────────────────────────────────────────────────────────────────

def avg_words(chunks):
    return sum(len(c.split()) for c in chunks) / len(chunks)


def main():
    text = DOC_PATH.read_text(encoding="utf-8")
    total_words = len(text.split())
    test_set = json.loads((DAY_DIR / "test_set.json").read_text(encoding="utf-8"))

    print(f"Corpus: {total_words} words\n")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Build one index per strategy and remember the chunks so we can inspect them.
    indexes, chunk_sets = {}, {}
    for name, fn in STRATEGIES.items():
        chunks = fn(text)
        chunk_sets[name] = chunks
        print(f"[{name:<11}] {len(chunks):>3} chunks | avg {avg_words(chunks):5.1f} words/chunk -> embedding...")
        indexes[name] = build_collection(client, name, chunks)
    print()

    # Run every question against every index; store the top-K retrieved chunks.
    results = []
    for item in test_set:
        row = {
            "id": item["id"],
            "question": item["question"],
            "doc_position": item["doc_position"],
            "answerable": item["answerable"],
            "gold_phrases": item.get("gold_phrases"),
            "retrieval": {},
        }
        for name, collection in indexes.items():
            res = collection.query(query_texts=[item["question"]], n_results=TOP_K)
            row["retrieval"][name] = {
                "ids": res["ids"][0],
                "documents": res["documents"][0],
                "distances": res["distances"][0],
            }
        results.append(row)
        print(f"{item['id']:<4} retrieved top-{TOP_K} from all 3 indexes")

    stats = {name: {"n_chunks": len(chunk_sets[name]),
                    "avg_words": round(avg_words(chunk_sets[name]), 1)}
             for name in STRATEGIES}

    out = {"top_k": TOP_K, "stats": stats, "results": results}
    (DAY_DIR / "run_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved -> {DAY_DIR / 'run_results.json'}")


if __name__ == "__main__":
    main()
