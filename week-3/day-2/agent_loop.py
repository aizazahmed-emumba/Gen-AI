"""
Week 3 - Day 2 (Course Day 12) - the explicit ReAct agent loop.

    DECIDE next action  →  EXECUTE it  →  OBSERVE the result  →  (loop) → STOP

This is ReAct made literal: each step the model REASONS about what to do next
(returns an action + a `reason`), we ACT (run a validated tool), it OBSERVES the
result, and re-decides. Two actions end the loop: `answer` and `refuse`.

Why an explicit JSON action instead of native tool-calling (Day 11)? Because the
task wants a *clear* loop over four named actions — retrieve / tool / answer /
refuse — and refuse/answer aren't "tools". Making the decision an explicit object
lets us LOG every decision and show exactly why the agent did what it did.

SHORT-TERM MEMORY is injected into the DECIDE prompt as "known context". That's
what lets follow-ups resolve ("food there?") — and, being lossy, what will
occasionally push the agent to the wrong city/budget (demonstrated in tests).

Validation (Day-11 `validate_args`) still gates every retrieve/tool call; an
invalid call becomes an observation the model can react to (self-correction).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))          # repo root (common)
sys.path.insert(0, str(Path(__file__).parent.parent / "day-1"))       # Day-11 tools
from common.groq_client import ask
import tools

MODEL = "openai/gpt-oss-120b"
MAX_STEPS = 4

DECIDE_PROMPT = """You are a travel assistant AGENT for Berlin, Paris, Amsterdam, Rome, and Barcelona. Decide the SINGLE next action to take.

Known context from earlier turns (may be empty): {memory}

Observations gathered so far this turn (tool results): {observations}

User's current message: "{query}"

Choose ONE action:
- "retrieve": search the travel database. Fields: city (one of the 5 supported), and optionally category (food|art|sightseeing), price_level (cheap|medium|expensive). Use for any what-to-see/eat/do question.
- "tool": compute a trip budget. Field: budget_args = {{days, travelers, daily_food, daily_activities, one_off_per_person}}. Use for any cost math.
- "answer": you have enough (from observations) to reply. Field: answer (ground it in the observations; do not invent places/prices).
- "refuse": out of scope (a city we don't cover, or not a travel question). Field: answer (a brief explanation).

Return ONLY JSON:
{{"action": "...", "reason": "<why this action>", "city": "...", "category": "...", "price_level": "...", "budget_args": {{...}}, "answer": "..."}}"""


def decide(query, memory, observations):
    obs = json.dumps(observations)[:1500] if observations else "(none yet)"
    raw = ask(DECIDE_PROMPT.format(memory=memory or "(none)", observations=obs, query=query),
              model=MODEL, temperature=0.0, response_format={"type": "json_object"})
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "answer", "reason": "decider returned invalid JSON",
                "answer": "Sorry, I had trouble processing that."}


def run_turn(query, memory, max_steps=MAX_STEPS):
    """Run the ReAct loop for one user turn. Returns (answer, steps)."""
    observations, steps = [], []

    for _ in range(max_steps):
        d = decide(query, memory, observations)
        action = d.get("action")
        rec = {"action": action, "reason": d.get("reason", "")}

        if action == "retrieve":
            args = {k: d[k] for k in ("city", "category", "price_level") if d.get(k)}
            ok, reason, clean = tools.validate_args("find_places", args)
            if not ok:
                rec["rejected"] = reason
                observations.append({"retrieve_error": reason})
            else:
                res = tools.find_places(**clean)
                rec["args"] = clean
                rec["observed"] = f"{res['count']} places"
                rec["observed_detail"] = [f"{p['title']} ({p['price_level']})" for p in res["places"]]
                observations.append({"find_places": clean, "result": res})
            steps.append(rec)
            continue

        if action == "tool":
            args = d.get("budget_args", {})
            ok, reason, clean = tools.validate_args("estimate_trip_budget", args)
            if not ok:
                rec["rejected"] = reason
                observations.append({"budget_error": reason})
            else:
                res = tools.estimate_trip_budget(**clean)
                rec["args"] = clean
                rec["observed"] = res
                rec["observed_detail"] = [f"total €{res['total_eur']} (€{res['per_person_eur']}/person)"]
                observations.append({"estimate_trip_budget": clean, "result": res})
            steps.append(rec)
            continue

        # answer / refuse (or unknown) end the loop
        rec["final"] = action
        steps.append(rec)
        return d.get("answer", ""), steps

    return "I couldn't complete that within the allowed steps.", steps
