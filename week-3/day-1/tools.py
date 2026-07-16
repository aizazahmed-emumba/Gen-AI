"""
Week 3 - Day 1 (Course Day 11) - Tool calling & controlled execution.

tools.py — the two tools the agent can call, their SCHEMAS, and a strict
validator. Everything here is the "controlled execution" half of the topic:
the LLM only ever *requests* a tool with arguments; this module decides whether
the request is legal and then runs deterministic Python.

TWO TOOLS (as the task asks):
  1. estimate_trip_budget  — DETERMINISTIC calculation. Pure arithmetic, so the
                             answer is exact and auditable (vs. an LLM that
                             *approximates* multi-step math).
  2. find_places           — RETRIEVAL. Filters the Day-5 Qdrant travel store by
                             city/category. Returns real rows, so the model can't
                             invent hotels/prices (the Day-5 hallucination).

WHY THE SCHEMA MATTERS (concepts 2 & 5):
  The JSON schema is BOTH a contract and a security boundary. `city` is an enum,
  so the model can't ask us to search "'; DROP TABLE" or an arbitrary string —
  the validator rejects anything off-menu. `days`/`travelers` have numeric
  bounds, so a poisoned `days: -5` or `days: 99999` is refused, not executed.
  Validation is where "the LLM asked for X" becomes "X is safe to run".
"""

import sys
from pathlib import Path

# reuse the Day-5 travel vector store (Qdrant) for the retrieval tool
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "week-2" / "day-5"))
import config as t_config   # day-5 config (CITIES, CATEGORIES, PRICE_LEVELS)
import store as t_store     # day-5 Qdrant store


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1 — deterministic calculator
# ─────────────────────────────────────────────────────────────────────────────

def estimate_trip_budget(days, travelers, daily_food, daily_activities, one_off_per_person=0):
    """Total trip cost = (food+activities) per day, per traveler, over the trip,
    plus a one-off per-person cost (e.g. a museum pass). Deterministic."""
    per_day_per_person = daily_food + daily_activities
    total = per_day_per_person * days * travelers + one_off_per_person * travelers
    return {
        "total_eur": round(total, 2),
        "per_person_eur": round(total / travelers, 2) if travelers else None,
        "breakdown": {
            "days": days, "travelers": travelers,
            "daily_food": daily_food, "daily_activities": daily_activities,
            "one_off_per_person": one_off_per_person,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2 — retrieval / metadata filter (wraps the Day-5 Qdrant store)
# ─────────────────────────────────────────────────────────────────────────────

def find_places(city, category=None, price_level=None, limit=5):
    """Return real places from the travel DB, filtered by city (+ optional
    category). price_level is a soft hint in the query text, not a hard filter
    (the Day-5 lesson: price labels are noisy)."""
    where = {"city": {city}}
    if category:
        where["category"] = {category}
    query = " ".join(x for x in [price_level, category or "things to do", "in", city] if x)
    hits = t_store.search(query, where=where, k=limit)
    return {
        "count": len(hits),
        "places": [{"title": h["title"], "category": h["category"],
                    "price_level": h["price_level"], "url": h["url"],
                    "text": h["text"][:280]} for h in hits],
    }


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS — the contract shown to the LLM (OpenAI/Groq function-calling format)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFS = [
    {"type": "function", "function": {
        "name": "estimate_trip_budget",
        "description": "Compute the total cost of a trip from per-day and one-off "
                       "costs. Use this for ANY budget/cost arithmetic — do not do "
                       "the math yourself.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "number of days (1-60)"},
            "travelers": {"type": "integer", "description": "number of people (1-20)"},
            "daily_food": {"type": "number", "description": "food cost per person per day (EUR)"},
            "daily_activities": {"type": "number", "description": "activities cost per person per day (EUR)"},
            "one_off_per_person": {"type": "number", "description": "one-time per-person cost, e.g. a pass (EUR); default 0"},
        }, "required": ["days", "travelers", "daily_food", "daily_activities"]},
    }},
    {"type": "function", "function": {
        "name": "find_places",
        "description": "Search the travel database for real places in a supported city. "
                       "Use this for ANY question about what to see/eat/do — do not "
                       "answer from your own memory.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "enum": t_config.CITIES},
            "category": {"type": "string", "enum": t_config.CATEGORIES},
            "price_level": {"type": "string", "enum": t_config.PRICE_LEVELS},
            "limit": {"type": "integer", "description": "max results (1-10), default 5"},
        }, "required": ["city"]},
    }},
]

TOOL_FUNCS = {"estimate_trip_budget": estimate_trip_budget, "find_places": find_places}


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION — the security + correctness gate on every tool call
# ─────────────────────────────────────────────────────────────────────────────

def validate_args(name, args):
    """Return (ok, reason, cleaned_args). Rejects unknown tools, missing required
    args, wrong types, out-of-range numbers, and off-enum strings (the last is our
    defense against parameter poisoning / tool hijacking)."""
    if name not in TOOL_FUNCS:
        return False, f"unknown tool '{name}'", None
    if not isinstance(args, dict):
        return False, "arguments are not a JSON object", None

    if name == "estimate_trip_budget":
        req = ["days", "travelers", "daily_food", "daily_activities"]
        for k in req:
            if k not in args:
                return False, f"missing required arg '{k}'", None
        clean = {}
        try:
            clean["days"] = int(args["days"])
            clean["travelers"] = int(args["travelers"])
            clean["daily_food"] = float(args["daily_food"])
            clean["daily_activities"] = float(args["daily_activities"])
            clean["one_off_per_person"] = float(args.get("one_off_per_person", 0) or 0)
        except (TypeError, ValueError):
            return False, "a numeric arg was not a number", None
        if not (1 <= clean["days"] <= 60):
            return False, f"days {clean['days']} out of range 1..60", None
        if not (1 <= clean["travelers"] <= 20):
            return False, f"travelers {clean['travelers']} out of range 1..20", None
        for k in ("daily_food", "daily_activities", "one_off_per_person"):
            if clean[k] < 0:
                return False, f"{k} cannot be negative", None
        return True, "ok", clean

    if name == "find_places":
        city = args.get("city")
        if city not in t_config.CITIES:                       # enum gate = anti-hijack
            return False, f"city '{city}' is not a supported city {t_config.CITIES}", None
        clean = {"city": city}
        if args.get("category") is not None:
            if args["category"] not in t_config.CATEGORIES:
                return False, f"category '{args['category']}' not in {t_config.CATEGORIES}", None
            clean["category"] = args["category"]
        if args.get("price_level") is not None:
            if args["price_level"] not in t_config.PRICE_LEVELS:
                return False, f"price_level '{args['price_level']}' not in {t_config.PRICE_LEVELS}", None
            clean["price_level"] = args["price_level"]
        limit = args.get("limit", 5)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        clean["limit"] = max(1, min(limit, 10))
        return True, "ok", clean

    return False, "no validator for tool", None
