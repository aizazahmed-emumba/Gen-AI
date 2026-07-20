"""
Week 3 - Day 2 (Course Day 12) - Agent patterns & memory.

memory.py — LIGHTWEIGHT SHORT-TERM MEMORY as a rolling summary.

Instead of replaying the entire transcript every turn (which grows without bound
and costs tokens), we keep ONE short summary of the conversation so far and update
it after each turn. The agent reads this summary to resolve follow-ups like
"what about food THERE?" (coreference) and to carry preferences ("cheap", "3 days").

THE DOUBLE-EDGED SWORD (the lesson):
  * Short-term summary HELPS: cheap context for continuity, resolves pronouns.
  * Short-term summary HURTS: it is LOSSY and STICKY. It compresses away nuance and
    keeps stale facts around, so an old city or an old budget preference can bleed
    into a new turn where it no longer applies. We will see this cause wrong
    decisions in the tests — by design, to show the failure mode.

(Long-term memory = a persistent store across sessions/users, e.g. a vector DB of
past interactions. We don't build it here; the task asks only for short-term. The
same helps/hurts trade-off applies, amplified: stale long-term facts are worse.)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

MODEL = "openai/gpt-oss-120b"

SUMMARIZE_PROMPT = """Update the running summary of a travel-planning conversation.
Keep it to 1-2 sentences. Capture the ACTIVE city, trip length, budget preference,
and interests the user currently cares about.

Previous summary: {prev}

Latest exchange:
User: {user}
Assistant: {answer}

Updated summary:"""


def update(prev_summary, user_msg, answer):
    prev = prev_summary or "(none yet)"
    return ask(SUMMARIZE_PROMPT.format(prev=prev, user=user_msg, answer=answer[:500]),
               model=MODEL, temperature=0.0).strip()
