import sys
import json
import re
import math
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

import ollama
from common.groq_client import ask

DAY4_DIR = Path(__file__).parent
DAY3_PDFS_DIR = DAY4_DIR.parent / "day-3" / "pdfs"

PDF_SOURCES = {
    "nist_sp800-53r5.pdf": DAY3_PDFS_DIR / "nist_sp800-53r5_extracted.txt",
    "moby_dick.pdf": DAY3_PDFS_DIR / "moby_dick_extracted.txt",
}

# mxbai-embed-large (334M) replaces nomic-embed-text (137M) — 2.4x bigger, the
# 2nd most-used embedding model on Ollama, benchmarked as SOTA for its size
# class on MTEB. Its native context length is actually SMALLER than
# nomic-embed-text's (512 vs 2048 tokens), so our shrink-and-retry fallback in
# embed_text() matters more here, not less.
EMBED_MODEL = "mxbai-embed-large"
# Answer model: llama-3.1-8b-instant. We tested the hypothesis that a bigger
# answer model would fix our ~3 suspected GENERATION failures (answer present
# in the retrieved chunks, but the 8B refused "NOT IN DOCUMENT"). Result on the
# 12 questions we could measure before the bigger models hit their daily quota:
# a WASH — llama-3.3-70b fixed one refusal (Q3) but introduced a new one (Q6,
# where the 8B had correctly extracted "System Backup" from page 152 and the
# 70B refused). So the generation failures are marginal/noisy, not a systematic
# capability gap, and a bigger answer model isn't the lever. Reverted to 8B,
# which is also the model our best full-25 result (16/25) used and has no daily
# quota cap (only per-minute), keeping future experiments unblocked.
ANSWER_MODEL = "llama-3.1-8b-instant"
TOP_K = 5


def _slug(name):
    return name.replace("/", "_")


# Cache files are named per-model so switching models doesn't clobber a previous
# model's already-computed (and possibly still wanted) results.
EMBEDDINGS_CACHE = DAY4_DIR / f"embeddings_cache_{_slug(EMBED_MODEL)}.json"
LLM_ONLY_CACHE = DAY4_DIR / f"llm_only_cache_{_slug(ANSWER_MODEL)}.json"

# Same boilerplate-stripping as Day 3 — the NIST PDF repeats a running
# header/footer on every page that would otherwise pollute embeddings just
# like it polluted BM25's keyword scoring.
BOILERPLATE_PATTERNS = [
    re.compile(r"NIST SP 800-53,\s*REV\.\s*5.*?ORGANIZATIONS\s*", re.DOTALL),
    re.compile(r"_{10,}\s*"),
    re.compile(r"CHAPTER \w+\s+PAGE \d+\s*"),
    re.compile(r"This publication is available free of charge from:?\s*\S+\s*"),
    re.compile(r"APPENDIX \w+\s*PAGE \d+\s*"),
]


def clean_boilerplate(text):
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


# ─── Step 1: load each PDF's extracted text, split into pages, then into ────
# ─── smaller sub-chunks within each page ────────────────────────────────────
# A whole-page chunk (~500-600 words) gets ONE embedding representing the
# AVERAGE meaning of everything on it. If a page is mostly about one thing but
# mentions the actual answer in passing (e.g. "Pequod" named once on a page
# that's mostly about OTHER whaling ships), that one relevant sentence gets
# diluted into the page's overall vector and stops looking distinctly
# relevant. Splitting each page into smaller, single-idea chunks — with a
# little overlap so a fact sitting right at a chunk boundary isn't cut in
# half — lets each embedding represent one specific idea instead of a blend.
CHUNK_WORDS = 180
CHUNK_OVERLAP_WORDS = 40


def split_into_word_chunks(text, chunk_words=CHUNK_WORDS, overlap_words=CHUNK_OVERLAP_WORDS):
    words = text.split()
    if len(words) <= chunk_words:
        return [text]
    step = chunk_words - overlap_words
    pieces = []
    start = 0
    while start < len(words):
        pieces.append(" ".join(words[start:start + chunk_words]))
        if start + chunk_words >= len(words):
            break
        start += step
    return pieces


# The NIST PDF's References appendix (PDF pages 401-420) is pure bibliography —
# dozens of repeated "NIST Special Publication (SP) 800-XX" citations, packed
# densely with no actual control content. It has now caused the exact same
# "dense boilerplate-adjacent page wins retrieval for the wrong reasons"
# failure THREE times across two totally different retrieval methods: BM25's
# raw term frequency, BM25's IDF weighting (Day 3), and cosine similarity over
# embeddings (Day 4, Q17's "chapter title" question pulled 3 of these pages
# instead of the correct Moby-Dick page). No question in our test set could
# ever legitimately be answered from a bibliography, so excluding it outright
# is safe and directly addresses a proven repeat offender rather than
# patching around its symptoms again.
EXCLUDED_PAGE_RANGES = {
    "nist_sp800-53r5.pdf": [(401, 420)],
}


def is_excluded(pdf_name, page_num):
    return any(start <= page_num <= end for start, end in EXCLUDED_PAGE_RANGES.get(pdf_name, []))


def load_chunks():
    chunks = []
    for pdf_name, txt_path in PDF_SOURCES.items():
        raw = txt_path.read_text(encoding="utf-8")
        pages = re.split(r"<<<PAGE (\d+)>>>", raw)[1:]
        for i in range(0, len(pages), 2):
            page_num = pages[i]
            if is_excluded(pdf_name, int(page_num)):
                continue
            page_text = pages[i + 1].strip()
            cleaned = clean_boilerplate(page_text)
            # Filter on the CLEANED length, not the raw length — a stub page like
            # "Control Enhancements: None. References: None." plus boilerplate
            # header easily clears 30 raw chars, but is nearly content-free once
            # the header is stripped. These degenerate short chunks turned out to
            # produce misleadingly high embedding similarity to unrelated
            # queries (the same "junk page pollutes retrieval" failure mode we
            # hit with BM25 in Day 3, just manifesting differently here).
            if len(cleaned) < 300:
                continue
            for chunk_index, piece in enumerate(split_into_word_chunks(cleaned)):
                if len(piece) < 80:
                    continue  # tiny trailing fragment from the split, not worth its own embedding
                chunks.append({
                    "pdf": pdf_name,
                    "page": int(page_num),
                    "chunk_index": chunk_index,
                    "text": piece,
                })
    return chunks


# ─── Step 2: embed every chunk (once), caching to disk ───────────────────────
# Embedding ~1000 pages takes a while even running locally, and the vectors
# never change unless the source text changes — so compute once, save to
# disk, and reuse on every future run instead of re-embedding from scratch.

def embed_text(text, _shrink=0):
    # Tried prefixing inputs with nomic-embed-text's documented "search_query: "
    # / "search_document: " task instructions — reverted. Measured result was a
    # wash (10/25 -> 9/25): it shifted the whole embedding space, which fixed
    # nothing and made NIST's dense bibliography pages rank higher for some
    # queries that used to correctly retrieve Moby-Dick pages instead. Real
    # measurement beat documented best practice here — see day-4 report for
    # the full comparison.
    #
    # nomic-embed-text's base context length is 2048 tokens in its own tokenizer
    # (a BERT-style tokenizer, which segments dense/bracket-heavy NIST text into
    # more pieces than our tiktoken-based size estimate suggests) — a few of our
    # denser pages exceeded that even after raising num_ctx to 8192, and which
    # specific pages fail isn't predictable from our own token counts. Rather
    # than guess a safe chunk size upfront, shrink and retry on failure —
    # guarantees every chunk eventually embeds, at the cost of some truncated
    # content for the rare oversized page.
    try:
        response = ollama.embed(model=EMBED_MODEL, input=text, options={"num_ctx": 8192})
        return response["embeddings"][0]
    except ollama.ResponseError as e:
        if "context length" not in str(e) or _shrink >= 4:
            raise
        half = text[: len(text) // 2]
        print(f"    (chunk too large for embedding model, truncating and retrying: {len(text)} -> {len(half)} chars)")
        return embed_text(half, _shrink=_shrink + 1)


def build_chunk_embeddings(chunks):
    cache = {}
    if EMBEDDINGS_CACHE.exists():
        cache = json.loads(EMBEDDINGS_CACHE.read_text(encoding="utf-8"))

    for i, chunk in enumerate(chunks):
        key = f"{chunk['pdf']}#p{chunk['page']}#c{chunk['chunk_index']}"
        if key in cache:
            chunk["embedding"] = cache[key]
            continue
        chunk["embedding"] = embed_text(chunk["text"])
        cache[key] = chunk["embedding"]
        if (i + 1) % 50 == 0 or i == len(chunks) - 1:
            print(f"  embedded {i + 1}/{len(chunks)} chunks...")
            EMBEDDINGS_CACHE.write_text(json.dumps(cache), encoding="utf-8")

    EMBEDDINGS_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return chunks


# ─── Step 3: cosine similarity + top-k retrieval, implemented by hand ────────
# cosine_similarity(a, b) = (a . b) / (|a| * |b|)
# This measures the ANGLE between two vectors, not their length — so a short
# chunk and a long chunk pointing in the same "semantic direction" still score
# as similar, unlike a raw dot product which would just favor bigger vectors.

def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve(query, chunks, k=TOP_K):
    query_embedding = embed_text(query)
    scored = [
        (cosine_similarity(query_embedding, chunk["embedding"]), chunk)
        for chunk in chunks
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(score, chunk) for score, chunk in scored[:k]]


# ─── Step 4: two ways of answering the same question ─────────────────────────
# The LLM-only condition never touches chunks, embeddings, or retrieval at all —
# it's the exact same prompt/model/temperature every single experiment we run
# here. Re-calling it every time we're only changing something on the RAG side
# (chunk size, prefixes, top-k, ...) is 25 wasted Groq calls per run for a
# result that isn't supposed to change. Cache it once per question, by ID, and
# reuse across every future experiment on this test set.

def load_llm_only_cache():
    if LLM_ONLY_CACHE.exists():
        return json.loads(LLM_ONLY_CACHE.read_text(encoding="utf-8"))
    return {}


def get_llm_only_answer(qid, question, cache):
    if qid in cache:
        return cache[qid]
    answer = answer_llm_only(question)
    cache[qid] = answer
    LLM_ONLY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return answer


def answer_llm_only(question):
    prompt = f"Answer the following question directly, based on what you already know.\n\nQUESTION: {question}"
    return ask(prompt, model=ANSWER_MODEL, temperature=0.0)


def answer_with_rag(question, retrieved):
    context = "\n\n---\n\n".join(
        f"[Source: {chunk['pdf']}, page {chunk['page']}]\n{chunk['text']}"
        for _, chunk in retrieved
    )
    prompt = (
        "Answer the question using ONLY the excerpts below. Cite the page number(s) you used, "
        "like (Source: page N). If the answer is not present in the excerpts, respond with exactly: "
        '"NOT IN DOCUMENT".\n\n'
        f"EXCERPTS:\n{context}\n\nQUESTION: {question}"
    )
    return ask(prompt, model=ANSWER_MODEL, temperature=0.0)


def main():
    print("Loading and chunking PDFs into pages, then into smaller sub-chunks...")
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks (~{CHUNK_WORDS} words each).")

    print("\nBuilding/loading chunk embeddings (cached to disk)...")
    chunks = build_chunk_embeddings(chunks)

    test_set = json.loads((DAY4_DIR / "test_set.json").read_text(encoding="utf-8"))
    llm_only_cache = load_llm_only_cache()

    out_path = DAY4_DIR / "run_results.json"
    results = []
    for item in test_set:
        qid, question = item["id"], item["question"]
        print(f"\n{'=' * 70}\n[{qid}] {question}")

        llm_only_answer = get_llm_only_answer(qid, question, llm_only_cache)
        print(f"  [LLM-only]: {llm_only_answer.strip()[:200]}")

        retrieved = retrieve(question, chunks)
        retrieved_labels = [f"{c['pdf']}#p{c['page']}.{c['chunk_index']} (sim={score:.3f})" for score, c in retrieved]
        print(f"  retrieved: {retrieved_labels}")

        rag_answer = answer_with_rag(question, retrieved)
        print(f"  [RAG]: {rag_answer.strip()[:200]}")

        results.append({
            "id": qid,
            "question": question,
            "answerable": item["answerable"],
            "expected_answer": item["expected_answer"],
            "key_terms": item.get("key_terms"),
            "source_pdf": item["source_pdf"],
            "llm_only_answer": llm_only_answer,
            "retrieved_chunks": retrieved_labels,
            "rag_answer": rag_answer,
        })
        # Save after every question, not just at the end — a mid-run rate-limit
        # crash (which has happened) otherwise loses ALL RAG answers computed so
        # far, since RAG answers aren't independently cached like LLM-only ones.
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSaved raw run results to {out_path}")


if __name__ == "__main__":
    main()
