"""
generator.py — final answer generation (Groq), grounded in the retrieved chunks.

Grounding discipline carried over from Day 9:
  * answer ONLY from the provided passages,
  * cite the passage numbers used (light citations),
  * if context was judged insufficient, say so honestly instead of inventing an
    itinerary from the model's travel memory.
A `duration_days` preference, if present, shapes the answer (e.g. a 3-day plan).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

import config

SYSTEM = ("You are a grounded travel assistant. Use ONLY the numbered passages provided. "
          "Cite the passages you use with [n]. Do not invent places, prices, or hours "
          "that are not in the passages. Be concrete and concise.")

PROMPT = """User request: {query}

Extracted preferences: {prefs}

Retrieved passages:
{passages}

Write a helpful, grounded answer to the request using ONLY these passages{plan}.
Cite passages as [n]. If the passages don't cover part of the request, say so briefly."""


def _format(hits):
    return "\n\n".join(
        f"[{i+1}] ({h['city']} · {h['category']} · {h['price_level']}) {h['text'][:500]}"
        for i, h in enumerate(hits))


def generate(query, prefs, hits, verdict):
    # Refuse cleanly when we genuinely have nothing to ground on.
    if not hits or verdict == "context_insufficient":
        if not hits:
            return ("I couldn't find anything in my travel sources matching that request. "
                    "Try a different city (I cover Berlin, Paris, Amsterdam, Rome, Barcelona) "
                    "or loosen the constraints.")
        # we have some hits but the judge was unsure — answer WITH a caveat, still grounded
    plan = ""
    if prefs.get("duration_days"):
        plan = f", organized as a {prefs['duration_days']}-day plan"

    answer = ask(PROMPT.format(query=query, prefs={k: v for k, v in prefs.items() if k != "_raw"},
                               passages=_format(hits), plan=plan),
                 model=config.GROQ_MODEL, temperature=0.3, system=SYSTEM)
    if verdict == "context_insufficient":
        answer = ("_Note: retrieval confidence was low, so this answer may be partial._\n\n" + answer)
    return answer
