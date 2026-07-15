"""
Week 2 - Day 5 (Course Day 10) - Preference-Aware Travel RAG Assistant.

config.py — the single source of truth. Every other module imports paths and
constants from here, so there are no magic strings scattered around the codebase.

CORPUS: Wikivoyage city articles. Why Wikivoyage?
  * It IS travel content (not a generic web page we bend into travel data).
  * CC BY-SA licensed and offers a clean API — no scraping-ethics or anti-bot issues.
  * It is structured into See / Do / Eat / Drink sections, which map directly onto
    the required `category` and `price_level` metadata — real structure, not faked.
"""

from pathlib import Path

DAY_DIR = Path(__file__).parent
INDEX_DIR = DAY_DIR / "index"          # the Qdrant on-disk store lives here
INDEX_DIR.mkdir(exist_ok=True)

# Qdrant embedded (local, on-disk) — no server/Docker. Stores vectors AND payload
# (metadata) together, and filters natively, so there is no separate meta.json.
QDRANT_PATH = INDEX_DIR / "qdrant"
COLLECTION = "travel"

# ── Models ───────────────────────────────────────────────────────────────────
EMBED_MODEL = "BAAI/bge-small-en-v1.5"          # 384-dim, in-process, Apache-2.0
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
GROQ_MODEL = "openai/gpt-oss-120b"              # query understanding, judge, answer

# ── Corpus: fixed list of travel URLs (one Wikivoyage article per city) ───────
CITIES = ["Berlin", "Paris", "Amsterdam", "Rome", "Barcelona"]
WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"


def city_url(city):
    return f"https://en.wikivoyage.org/wiki/{city}"


SOURCES = [{"city": c, "url": city_url(c)} for c in CITIES]

# ── Ingestion / retrieval knobs ───────────────────────────────────────────────
CHUNK_WORDS = 160          # target chunk size (paragraph-packed)
CHUNK_MIN_WORDS = 25       # drop/merge fragments smaller than this
TOP_K_SEMANTIC = 30        # stage-1 recall net before filtering/reranking
TOP_K_FINAL = 5            # chunks handed to the answer generator

# Controlled vocabularies (so filters and the LLM agree on the same tokens)
CATEGORIES = ["food", "art", "sightseeing"]
PRICE_LEVELS = ["cheap", "medium", "expensive"]

# Which Wikivoyage sections we ingest, and the category each maps to.
# (Sleep/Buy/logistics sections are skipped — not relevant to the query types.)
SECTION_CATEGORY = {
    "see": "art_or_sightseeing",   # resolved per-listing: art if museum/gallery, else sightseeing
    "do": "sightseeing",
    "eat": "food",
    "drink": "food",
}
