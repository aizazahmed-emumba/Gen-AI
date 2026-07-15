"""
ingest.py — OFFLINE pipeline. Run once to build the index the app queries.

    Wikivoyage API → plain text → split by section → chunk → attach metadata
    → embed (bge-small) → FAISS index + metadata store (saved to ./index/)

The interesting part is METADATA DERIVATION. We don't invent city/category/
price_level — we read them off the document's real structure:
  * city         : which article we fetched.
  * category     : the Wikivoyage section (Eat/Drink→food, Do→sightseeing,
                   See→art if it's a museum/gallery, else sightseeing).
  * price_level  : the budget sub-section name if the city uses one
                   (Budget/Mid-range/Splurge); otherwise inferred from price
                   signals in the text ("free", "cheap", "luxury", …).
Chunks never cross a section boundary, so each chunk gets ONE honest label.
"""

import json
import re
import urllib.parse
import urllib.request

from qdrant_client import QdrantClient, models

import config
import embedder

HEADING_RE = re.compile(r"^(==+)\s*(.+?)\s*==+\s*$")
MONEY_SECTIONS = {"see", "do", "eat", "drink"}

ART_KEYWORDS = ("museum", "gallery", "galleries", "art", "exhibition", "sculpture", "painting")
CHEAP_HINTS = ("free", "no charge", "cheap", "budget", "inexpensive", "affordable", "hostel")
EXPENSIVE_HINTS = ("luxury", "upscale", "fine dining", "splurge", "expensive", "michelin", "high-end")
# budget sub-section names some cities DO use
PRICE_BY_SUBSECTION = {
    "budget": "cheap", "cheap": "cheap",
    "mid-range": "medium", "mid range": "medium", "moderate": "medium",
    "splurge": "expensive", "luxury": "expensive", "upscale": "expensive",
}


# ── 1. FETCH ──────────────────────────────────────────────────────────────────
def fetch_extract(city):
    """Return the article as clean plain text with '== Section ==' markers."""
    params = {"action": "query", "format": "json", "prop": "extracts",
              "explaintext": 1, "exsectionformat": "wiki", "titles": city, "redirects": 1}
    url = config.WIKIVOYAGE_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "TravelRAG/0.1 (course project)"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    page = next(iter(data["query"]["pages"].values()))
    return page.get("extract", "")


# ── 2. CLASSIFY (metadata derivation) ─────────────────────────────────────────
def resolve_category(section, text):
    if section in ("eat", "drink"):
        return "food"
    if section == "do":
        return "sightseeing"
    if section == "see":
        low = text.lower()
        return "art" if any(k in low for k in ART_KEYWORDS) else "sightseeing"
    return "sightseeing"


def resolve_price(subsection, text):
    sub = subsection.lower().strip()
    for key, level in PRICE_BY_SUBSECTION.items():
        if key in sub:
            return level
    low = text.lower()
    if any(h in low for h in EXPENSIVE_HINTS):
        return "expensive"
    if any(h in low for h in CHEAP_HINTS):
        return "cheap"
    return "medium"


# ── 3. SECTIONIZE + CHUNK ─────────────────────────────────────────────────────
def sectionize(text):
    """Yield (top_section, subsection, paragraph) for the money sections only."""
    top, sub = None, ""
    buf = []
    out = []

    def flush():
        para = " ".join(buf).strip()
        buf.clear()
        return para

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if buf and top in MONEY_SECTIONS:
                out.append((top, sub, flush()))
            else:
                buf.clear()
            name = m.group(2).strip()
            if len(m.group(1)) == 2:              # top-level section
                top, sub = name.lower(), ""
            else:                                  # sub-section
                sub = name
            continue
        if line.strip():
            buf.append(line.strip())
        elif buf:                                  # blank line = paragraph break
            if top in MONEY_SECTIONS:
                out.append((top, sub, flush()))
            else:
                buf.clear()
    if buf and top in MONEY_SECTIONS:
        out.append((top, sub, flush()))
    return [(t, s, p) for t, s, p in out if len(p.split()) >= 8]


def pack(paragraphs):
    """Pack same-section paragraphs into ~CHUNK_WORDS chunks (paragraph strategy)."""
    chunks, buf, meta = [], [], None
    for top, sub, para in paragraphs:
        changed = meta is not None and (top, sub) != meta
        big = sum(len(x.split()) for x in buf) + len(para.split()) > config.CHUNK_WORDS
        if buf and (changed or big):
            chunks.append((meta, " ".join(buf)))
            buf = []
        if not buf:
            meta = (top, sub)
        buf.append(para)
    if buf:
        chunks.append((meta, " ".join(buf)))
    return [(m, t) for m, t in chunks if len(t.split()) >= config.CHUNK_MIN_WORDS]


# ── 4. BUILD INDEX ────────────────────────────────────────────────────────────
def build():
    records = []
    for src in config.SOURCES:
        city, url = src["city"], src["url"]
        text = fetch_extract(city)
        chunks = pack(sectionize(text))
        for (section, sub), body in chunks:
            records.append({
                "id": f"{city}-{len(records)}",
                "text": body,
                "url": url,
                "city": city,
                "category": resolve_category(section, body),
                "price_level": resolve_price(sub, body),
                "section": section.capitalize(),
                "title": (sub or section.capitalize()),
            })
        print(f"[{city:<10}] {len([r for r in records if r['city']==city]):>3} chunks")

    print(f"\nEmbedding {len(records)} chunks with {config.EMBED_MODEL} ...")
    vecs = embedder.embed_documents([r["text"] for r in records])

    # Store vector + payload (metadata) TOGETHER in Qdrant. The payload is the whole
    # record, so there is no separate meta.json to keep in sync — Qdrant returns the
    # metadata with each hit and filters on it natively.
    client = QdrantClient(path=str(config.QDRANT_PATH))
    if client.collection_exists(config.COLLECTION):
        client.delete_collection(config.COLLECTION)
    client.create_collection(
        config.COLLECTION,
        vectors_config=models.VectorParams(size=vecs.shape[1], distance=models.Distance.COSINE),
    )
    client.upsert(config.COLLECTION, points=[
        models.PointStruct(id=i, vector=vecs[i].tolist(), payload=records[i])
        for i in range(len(records))
    ])

    from collections import Counter
    print(f"\nUpserted {client.count(config.COLLECTION).count} points -> {config.QDRANT_PATH.name}/")
    print("category :", dict(Counter(r["category"] for r in records)))
    print("price    :", dict(Counter(r["price_level"] for r in records)))
    print("city     :", dict(Counter(r["city"] for r in records)))
    client.close()   # release the on-disk lock so the app can open it


if __name__ == "__main__":
    build()
