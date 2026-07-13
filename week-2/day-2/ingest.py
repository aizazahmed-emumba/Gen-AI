"""
Week 2 - Day 2 (Course Day 7) - Ingestion with METADATA ATTACHMENT.

This is the foundation for the whole day. Query optimization and metadata
filtering both need ONE thing to already be true: every chunk in the vector DB
must carry structured metadata that describes WHERE it came from.

CORE IDEA — metadata at ingestion time
---------------------------------------
A vector DB stores, per chunk:
    (id, embedding vector, the raw text, a small dict of metadata)
The embedding lets us search by MEANING. The metadata lets us search by FACTS
we know for certain (which book, which page, which control, what date).
You can only attach metadata when you INGEST, because that's the only moment you
still know the chunk's origin (its page marker, its chapter heading, its source
file). Once it's an anonymous 384-float vector in the DB, that context is gone
forever unless you saved it as metadata. So: parse structure now, or lose it.

Our corpus is deliberately HETEROGENEOUS so filters actually mean something:
    - The Metamorphosis (Kafka, 1915)      fiction, prose, 3 parts
    - Moby Dick        (Melville, 1851)    fiction, 135 chapters (we take the opening)
    - NIST SP 800-53r5 (NIST, 2020)        technical standard, control catalog

The two extracted files carry REAL structure we can parse into metadata:
    <<<PAGE 42>>>            -> page number
    CHAPTER 3. The Spouter.  -> Moby Dick chapter/section
    AC-2 ACCOUNT MANAGEMENT  -> NIST control id + name
That is the whole trick: turn markers that already exist in the text into
queryable metadata fields, and strip them out of the chunk body so they don't
pollute the embedding.
"""

import re
from pathlib import Path

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import ollama

DAY_DIR = Path(__file__).parent
REPO = DAY_DIR.parent.parent
CHROMA_DIR = DAY_DIR / "chroma_db"
COLLECTION = "day7_mixed"

EMBED_MODEL = "mxbai-embed-large"   # same embedder as Days 5 & W2D1 -> results stay comparable
TARGET_CHARS = 1050                 # ~150 words/chunk, same size we settled on in W2D1

# Source files (reuse the Day-3 extractions) and how much of each to ingest.
# We slice the two big books to a content-rich region so embedding stays fast
# (~2 min) while the corpus is still big enough that filtering matters.
SOURCES = [
    {
        "path": REPO / "week-2/day-1/docs/metamorphosis.txt",
        "meta": {"source": "kafka", "title": "The Metamorphosis",
                 "author": "Franz Kafka", "doc_type": "fiction", "date": "1915"},
        "start_marker": None,        # take the whole novel
        "word_budget": None,
        "structure": "metamorphosis",
    },
    {
        "path": REPO / "week-1/day-3/pdfs/moby_dick_extracted.txt",
        "meta": {"source": "melville", "title": "Moby-Dick",
                 "author": "Herman Melville", "doc_type": "fiction", "date": "1851"},
        "start_marker": "Call me Ishmael",   # skip the title page / table of contents
        "word_budget": 45000,                # opening ~third of the novel
        "structure": "moby",
    },
    {
        "path": REPO / "week-1/day-3/pdfs/nist_sp800-53r5_extracted.txt",
        "meta": {"source": "nist", "title": "NIST SP 800-53r5",
                 "author": "NIST", "doc_type": "standard", "date": "2020-09"},
        "start_marker": "AC-1 POLICY AND PROCEDURES",  # skip front matter -> jump to the control catalog
        "word_budget": 45000,                          # the Access-Control-heavy region
        "structure": "nist",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 1) SLICE — read a source and keep only the region we care about
# ─────────────────────────────────────────────────────────────────────────────

def slice_text(raw, start_marker, word_budget):
    if start_marker:
        idx = raw.find(start_marker)
        if idx != -1:
            raw = raw[idx:]
    if word_budget:
        # Truncate to `word_budget` words WITHOUT collapsing whitespace — we must
        # keep the newlines, because the parser below relies on line boundaries to
        # find <<<PAGE>>> / CHAPTER / control markers. (Collapsing to single spaces
        # was the bug that gave 0 chunks.)
        count = 0
        for m in re.finditer(r"\S+", raw):
            count += 1
            if count >= word_budget:
                raw = raw[: m.end()]
                break
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# 2) PARSE STRUCTURE INTO (paragraph, live-metadata) PAIRS
#    As we walk the text top-to-bottom we keep a "current page" and "current
#    section" that update whenever we hit a marker line. Every paragraph we emit
#    inherits whatever page/section is current at that point. This is exactly how
#    a real ingestion pipeline tags chunks: sweep once, carry the context down.
# ─────────────────────────────────────────────────────────────────────────────

PAGE_RE = re.compile(r"<<<PAGE\s+(\d+)>>>")
MOBY_CH_RE = re.compile(r"^CHAPTER\s+(\d+)\.\s*(.*)$")
# NIST control heading, e.g. "AC-2 ACCOUNT MANAGEMENT" or "AU-6 AUDIT RECORD REVIEW"
NIST_CTRL_RE = re.compile(r"^([A-Z]{2}-\d+)\s+([A-Z][A-Z \-,/]+)$")


def parse_paragraphs(text, structure):
    """Yield (paragraph_text, {page, section}) as we sweep the sliced document."""
    page = None
    section = None
    buf = []

    def flush():
        para = " ".join(buf).strip()
        buf.clear()
        return para

    out = []
    for line in text.splitlines():
        stripped = line.strip()

        # -- page marker: update current page, don't emit it into the body --
        m = PAGE_RE.search(stripped)
        if m:
            if buf:
                out.append((flush(), {"page": page, "section": section}))
            page = int(m.group(1))
            continue

        # -- section markers differ per source --
        if structure == "moby":
            m = MOBY_CH_RE.match(stripped)
            if m:
                if buf:
                    out.append((flush(), {"page": page, "section": section}))
                section = f"Ch {int(m.group(1))}: {m.group(2).strip().rstrip('.')}"
                continue
        elif structure == "nist":
            m = NIST_CTRL_RE.match(stripped)
            if m:
                if buf:
                    out.append((flush(), {"page": page, "section": section}))
                section = f"{m.group(1)} {m.group(2).strip().title()}"
                continue
        elif structure == "metamorphosis":
            # the Gutenberg text marks its three parts with a lone Roman numeral
            if stripped in ("I", "II", "III"):
                if buf:
                    out.append((flush(), {"page": page, "section": section}))
                section = f"Part {stripped}"
                continue

        # -- blank line ends a paragraph --
        if stripped == "":
            if buf:
                out.append((flush(), {"page": page, "section": section}))
        else:
            buf.append(stripped)

    if buf:
        out.append((flush(), {"page": page, "section": section}))
    return [(p, m) for p, m in out if p]


# ─────────────────────────────────────────────────────────────────────────────
# 3) PACK paragraphs into ~TARGET_CHARS chunks WITHOUT crossing a section change.
#    Two birds, one stone:
#      * this is boundary-aware ("recursive"-style) chunking — the W2D1 winner
#        for structured docs, because a cut never lands mid-section; and
#      * because a chunk never spans two sections, it inherits ONE clean section
#        label, so the metadata stays honest.
# ─────────────────────────────────────────────────────────────────────────────

def split_long(para):
    """A single paragraph can be bigger than TARGET_CHARS (Kafka loves 600-word
    paragraphs). Split it on sentence boundaries, then hard-split any sentence
    that is still too long, so no piece can overflow the embedder's context."""
    if len(para) <= TARGET_CHARS:
        return [para]
    pieces, buf = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", para):
        while len(sent) > TARGET_CHARS:                 # pathological run-on -> hard cut
            pieces.append(sent[:TARGET_CHARS])
            sent = sent[TARGET_CHARS:]
        if len(buf) + len(sent) > TARGET_CHARS and buf:
            pieces.append(buf.strip())
            buf = ""
        buf += (" " if buf else "") + sent
    if buf.strip():
        pieces.append(buf.strip())
    return pieces


def pack_chunks(paragraphs):
    chunks = []
    buf, buf_meta = "", None
    for para, meta in paragraphs:
        for piece in split_long(para):      # never let one paragraph exceed the target
            section_changed = buf_meta is not None and meta["section"] != buf_meta["section"]
            too_big = len(buf) + len(piece) > TARGET_CHARS
            if buf and (section_changed or too_big):
                chunks.append((buf.strip(), buf_meta))
                buf, buf_meta = "", None
            if not buf:
                buf_meta = meta             # first paragraph fixes this chunk's page/section
            buf += (" " if buf else "") + piece
    if buf:
        chunks.append((buf.strip(), buf_meta))
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 4) EMBED + STORE  (metadata goes in alongside each vector)
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


def build():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(
        COLLECTION,
        embedding_function=OllamaEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )

    all_ids, all_docs, all_meta = [], [], []
    for src in SOURCES:
        raw = Path(src["path"]).read_text(encoding="utf-8", errors="ignore")
        raw = slice_text(raw, src["start_marker"], src["word_budget"])
        paras = parse_paragraphs(raw, src["structure"])
        chunks = pack_chunks(paras)
        n = len(chunks)
        for i, (text, struct_meta) in enumerate(chunks):
            meta = dict(src["meta"])                       # source/title/author/doc_type/date
            meta["section"] = struct_meta["section"] or "(front matter)"
            meta["page"] = struct_meta["page"] if struct_meta["page"] is not None else -1
            meta["position_pct"] = round(100 * i / max(n - 1, 1))  # 0..100 through this doc
            meta["chunk_index"] = i
            all_ids.append(f'{src["meta"]["source"]}-{i}')
            all_docs.append(text)
            all_meta.append(meta)
        avg_w = sum(len(c[0].split()) for c in chunks) / max(n, 1)
        print(f'[{src["meta"]["source"]:<9}] {n:>4} chunks | avg {avg_w:5.1f} words -> embedding...')

    # Chroma embeds in add(); do it in batches so we see progress and stay memory-light.
    B = 100
    for i in range(0, len(all_docs), B):
        collection.add(ids=all_ids[i:i+B], documents=all_docs[i:i+B], metadatas=all_meta[i:i+B])
        print(f"  embedded {min(i+B, len(all_docs))}/{len(all_docs)}")

    print(f"\nCollection '{COLLECTION}' built: {collection.count()} chunks total.")
    return collection


if __name__ == "__main__":
    build()
