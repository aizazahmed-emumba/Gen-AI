import sys
import json
import re
import math
from pathlib import Path
from collections import Counter

sys.path.append(str(Path(__file__).resolve().parents[2]))

from common.groq_client import ask

DAY3_DIR = Path(__file__).parent
PDF_SOURCES = {
    "nist_sp800-53r5.pdf": DAY3_DIR / "pdfs" / "nist_sp800-53r5_extracted.txt",
    "moby_dick.pdf": DAY3_DIR / "pdfs" / "moby_dick_extracted.txt",
}

MODEL_A = "llama-3.3-70b-versatile"
MODEL_B = "llama-3.1-8b-instant"

TOP_K = 5
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "who", "which", "does",
    "did", "do", "in", "of", "to", "and", "for", "on", "at", "by", "as", "that",
    "this", "it", "his", "her", "their", "be", "per", "its", "or", "with",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")

# The NIST PDF repeats a running header/footer on every single page ("NIST SP
# 800-53, REV. 5 ... SECURITY AND PRIVACY CONTROLS FOR INFORMATION SYSTEMS AND
# ORGANIZATIONS", a divider line, "CHAPTER X PAGE N", and the "available free
# of charge" boilerplate URL line). On short, mostly-empty pages (a stub with
# just "Control Enhancements: None. References: None.") that boilerplate can
# be MOST of the page's text — which breaks length-normalized retrieval
# scoring, since a few boilerplate word matches on a tiny page look like a
# strong match once divided by that page's (artificially small) real length.
# Stripping it before scoring fixes retrieval at the source instead of
# patching around it in the scoring formula.
BOILERPLATE_PATTERNS = [
    re.compile(r"NIST SP 800-53,\s*REV\.\s*5.*?ORGANIZATIONS\s*", re.DOTALL),
    re.compile(r"_{10,}\s*"),
    re.compile(r"CHAPTER \w+\s+PAGE \d+\s*"),
    re.compile(r"This publication is available free of charge from:?\s*\S+\s*"),
    re.compile(r"APPENDIX \w+\s*PAGE \d+\s*"),
]

# A document's own name ("NIST", "SP", "Rev") repeats constantly in citations
# and running text throughout a NIST publication without telling you anything
# about which specific page is relevant — drop it the same way "the"/"a" get
# dropped, since it's boilerplate vocabulary for this corpus, not a stopword
# in general English.
STOPWORDS |= {"nist", "sp", "rev"}


def clean_boilerplate(text):
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


# ─── Step 1: load each PDF's extracted text and split into per-page chunks ───

def load_chunks():
    chunks = []
    for pdf_name, txt_path in PDF_SOURCES.items():
        raw = txt_path.read_text(encoding="utf-8")
        pages = re.split(r"<<<PAGE (\d+)>>>", raw)[1:]  # alternating [num, text, num, text, ...]
        for i in range(0, len(pages), 2):
            page_num = pages[i]
            page_text = pages[i + 1].strip()
            if len(page_text) < 30:
                continue  # skip near-empty pages (blank/whitespace-only)
            clean_text = clean_boilerplate(page_text)
            tokens = [t for t in tokenize(clean_text) if t not in STOPWORDS]
            if not tokens:
                continue  # page was pure boilerplate/whitespace once cleaned
            chunks.append({
                "pdf": pdf_name,
                "page": int(page_num),
                "text": page_text,
                "term_freq": Counter(tokens),
                "length": len(tokens),
            })
    return chunks


# ─── Step 2: BM25 retrieval (no embeddings, no extra deps) ───────────────────
# A naive "count keyword matches" scorer fails here in two ways: (1) generic
# words like "control"/"system" appear on nearly every page, so word-dense
# pages dominate regardless of the actual question, and (2) a word that's rare
# across the document but happens to repeat 20+ times on one specific page
# (e.g. "NIST"/"SP" self-citations, clustered in the bibliography) can swamp
# the score for totally unrelated questions. BM25 — the ranking function real
# search engines (Elasticsearch, Lucene) use by default — fixes both: it caps
# how much repeated occurrences of one word can contribute (diminishing
# returns via the k1 term), and normalizes each page's length against the
# *average* page length across the whole corpus rather than its own length,
# so short stub pages can't fake relevance either.
BM25_K1 = 1.5
BM25_B = 0.75


def build_idf(chunks):
    doc_freq = Counter()
    for chunk in chunks:
        doc_freq.update(chunk["term_freq"].keys())
    n_docs = len(chunks)
    return {term: math.log((n_docs - df + 0.5) / (df + 0.5) + 1) for term, df in doc_freq.items()}


# NIST control IDs (e.g. "AC-2", "SC-7") are cited dozens of times throughout
# the document as cross-references ("Related Controls: AC-2, AC-3, ..."),
# which dilutes BM25's ability to tell "the page that defines AC-2" apart from
# "any page that merely mentions AC-2 in passing" — the real definition page
# ranked ~40-60th out of 492 in testing, well outside any reasonable top-k.
# Rather than keep tuning generic keyword scoring to chase this one pattern,
# it's more reliable (and more realistic — production RAG systems commonly do
# this) to special-case it: if a question names a specific control ID, look
# directly for the page where that ID appears as a heading (its definition),
# and guarantee that page is included before falling back to BM25 for the
# rest of the context.
CONTROL_ID_RE = re.compile(r"\b([A-Z]{2}-\d+)\b")


def find_control_heading_page(control_id, chunks):
    heading_re = re.compile(rf"^{re.escape(control_id)}\s+[A-Z]", re.MULTILINE)
    for chunk in chunks:
        if chunk["pdf"] == "nist_sp800-53r5.pdf" and heading_re.search(chunk["text"]):
            return chunk
    return None


def bm25_rank(q_tokens, chunks, idf):
    avg_length = sum(c["length"] for c in chunks) / len(chunks)
    scored = []
    for chunk in chunks:
        score = 0.0
        for t in q_tokens:
            tf = chunk["term_freq"].get(t, 0)
            if not tf:
                continue
            length_norm = 1 - BM25_B + BM25_B * (chunk["length"] / avg_length)
            score += idf.get(t, 0) * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * length_norm)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def retrieve(question, chunks, idf, k=TOP_K):
    q_tokens = set(t for t in tokenize(question) if t not in STOPWORDS)

    boosted = []
    for control_id in CONTROL_ID_RE.findall(question):
        page = find_control_heading_page(control_id, chunks)
        if page and page not in boosted:
            boosted.append(page)

    ranked = bm25_rank(q_tokens, chunks, idf)
    for chunk in ranked:
        if len(boosted) >= k:
            break
        if chunk not in boosted:
            boosted.append(chunk)
    return boosted[:k]


def build_context(retrieved_chunks):
    parts = []
    for c in retrieved_chunks:
        parts.append(f"[Source: {c['pdf']}, page {c['page']}]\n{c['text']}")
    return "\n\n---\n\n".join(parts)


PROMPT_TEMPLATE = """You are answering questions using ONLY the excerpts below, retrieved from a document search. \
The excerpts may or may not actually contain the answer.

If the answer is present in the excerpts, answer it directly and concisely.
If the answer is NOT present in the excerpts, respond with exactly: "NOT IN DOCUMENT" — do not guess or use \
outside knowledge.

EXCERPTS:
{context}

QUESTION: {question}"""


def run_question(question, context, model):
    prompt = PROMPT_TEMPLATE.format(context=context, question=question)
    return ask(prompt, model=model, temperature=0.0)


def main():
    print("Loading and chunking PDFs into pages...")
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} page-chunks total "
          f"({sum(1 for c in chunks if c['pdf'] == 'nist_sp800-53r5.pdf')} NIST, "
          f"{sum(1 for c in chunks if c['pdf'] == 'moby_dick.pdf')} Moby-Dick).")
    idf = build_idf(chunks)

    test_set = json.loads((DAY3_DIR / "test_set.json").read_text(encoding="utf-8"))

    results = []
    for item in test_set:
        qid, question = item["id"], item["question"]
        print(f"\n{'=' * 70}\n[{qid}] {question}")

        retrieved = retrieve(question, chunks, idf)
        context = build_context(retrieved)
        retrieved_labels = [f"{c['pdf']}#p{c['page']}" for c in retrieved]
        print(f"  retrieved: {retrieved_labels}")

        answer_a = run_question(question, context, MODEL_A)
        answer_b = run_question(question, context, MODEL_B)
        print(f"  [{MODEL_A}]: {answer_a.strip()[:200]}")
        print(f"  [{MODEL_B}]: {answer_b.strip()[:200]}")

        results.append({
            "id": qid,
            "question": question,
            "answerable": item["answerable"],
            "expected_answer": item["expected_answer"],
            "source_pdf": item["source_pdf"],
            "retrieved_chunks": retrieved_labels,
            "retrieved_context": context,
            "model_a": MODEL_A,
            "model_a_answer": answer_a,
            "model_b": MODEL_B,
            "model_b_answer": answer_b,
        })

    out_path = DAY3_DIR / "run_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved raw run results to {out_path}")


if __name__ == "__main__":
    main()
