"""
preferences.py — query understanding: user text -> structured preferences JSON.

    "3-day Berlin trip with cheap food and art"
        -> {"city":"Berlin","categories":["food","art"],
            "price_levels":["cheap"],"duration_days":3}

This is the bridge between fuzzy human intent and the hard metadata filters the
vector store understands. One Groq call does the extraction; then WE validate the
result against controlled vocabularies (config.CATEGORIES / PRICE_LEVELS / CITIES).
Validation matters: the retriever will FILTER on these values, so a hallucinated
category like "nightlife" must be dropped, not passed through — a bad filter value
would silently return zero results (the Day-9 quality-gate lesson, applied here).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

import config

SYSTEM = "You extract structured travel preferences from a user's request. Output JSON only."

PROMPT = """From the travel request, extract preferences as JSON with EXACTLY these keys:
- "cities": a JSON array of the cities the user wants to visit, each as its own string, exactly as named (do NOT restrict to any list, do NOT translate, do NOT combine two cities into one string). [] if no city is mentioned.
- "categories": a subset of {categories} (what the user is interested in); [] if unclear.
- "price_levels": a subset of {prices} (map "cheap/budget"->cheap, "mid-range"->medium, "luxury/fine dining"->expensive); [] if unspecified.
- "duration_days": integer number of days, or null.

Request: {query}

JSON:"""


def extract(query):
    raw = ask(PROMPT.format(query=query, cities=config.CITIES,
                            categories=config.CATEGORIES, prices=config.PRICE_LEVELS),
              model=config.GROQ_MODEL, temperature=0.0, system=SYSTEM,
              response_format={"type": "json_object"})
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        obj = {}

    # ── validate / normalize against the controlled vocabularies ──
    # Cities need care. A query can name ZERO, ONE, or SEVERAL cities, and each named
    # city is either SUPPORTED (in our corpus) or not. We must split those apart:
    #   * supported cities  -> we can serve them (filter retrieval to them);
    #   * unsupported cities -> we have no sources, must tell the user.
    # We refuse ONLY when the user named cities and NONE are supported. If some are
    # supported (e.g. "Paris and Rome", or "Berlin and Tokyo"), we proceed with those.
    # Defensive: even if the model returns a single "Paris and Rome" string, we split it.
    raw_cities = obj.get("cities", obj.get("city"))      # tolerate old singular key too
    items = raw_cities if isinstance(raw_cities, list) else ([raw_cities] if raw_cities else [])
    named = []
    for it in items:
        if isinstance(it, str):
            named += [p.strip() for p in re.split(r"\s+and\s+|,|&|/", it) if p.strip()]

    supported, unsupported = [], []
    for name in named:
        canon = next((c for c in config.CITIES if name.lower() == c.lower()), None)
        if canon and canon not in supported:
            supported.append(canon)
        elif not canon and name not in unsupported:
            unsupported.append(name)

    cats = [c for c in (obj.get("categories") or []) if c in config.CATEGORIES]
    prices = [p for p in (obj.get("price_levels") or []) if p in config.PRICE_LEVELS]

    days = obj.get("duration_days")
    days = days if isinstance(days, int) and 1 <= days <= 30 else None

    return {"cities": supported, "unsupported_cities": unsupported,
            "categories": cats, "price_levels": prices,
            "duration_days": days, "_raw": raw}
