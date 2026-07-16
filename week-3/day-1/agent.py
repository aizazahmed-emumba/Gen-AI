"""
Week 3 - Day 1 (Course Day 11) - the tool-calling AGENT loop.

This is the "controlled execution" orchestrator. The LLM never runs code — it only
emits a *request* to call a tool with arguments. We then:
    1. validate the arguments against the strict schema (reject if illegal),
    2. execute the real Python function ourselves,
    3. feed the result back as a `tool` message,
    4. let the model read the result and either call another tool or answer.

The loop is the standard function-calling pattern:
    user → [model: tool_calls?] → validate+run → tool result → [model again] → … → final text

Key safety properties:
  * tool_choice="auto" — the MODEL decides whether a tool is needed (task requirement).
  * every tool call passes through validate_args → a hijacked/poisoned call is
    rejected and the rejection is fed back (the model can recover or apologise).
  * max_iters caps the loop so a misbehaving model can't spin forever.

Everything is recorded in a `trace` so the report can show exactly what happened.
"""

import json
import sys
import time
from pathlib import Path

from groq import RateLimitError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import get_client, parse_retry_seconds

import tools

MODEL = "openai/gpt-oss-120b"
MAX_ITERS = 5

# STRONG prompt — pushes the model to always use the right tool (high reliability).
SYSTEM = (
    "You are a travel assistant for Berlin, Paris, Amsterdam, Rome, and Barcelona. "
    "You have two tools:\n"
    "- find_places: search the travel database for real places. Use it for ANY "
    "question about what to see/eat/do in a supported city. Do NOT answer such "
    "questions from memory.\n"
    "- estimate_trip_budget: compute trip costs. Use it for ANY budget/cost math. "
    "Do NOT do the arithmetic yourself.\n"
    "If a question needs neither (a greeting, a general question, or a city we don't "
    "cover), answer directly and say what you can help with. Never invent place "
    "names, prices, or facts."
)

# NEUTRAL prompt — tools are AVAILABLE but the model uses its own judgment. This is
# where the "skipped tool" failure mode shows up (the model answers easy math /
# famous facts from memory instead of calling a tool).
SYSTEM_NEUTRAL = (
    "You are a helpful travel assistant. You may use the available tools if you "
    "think they help, or answer directly."
)


def _create(client, messages):
    """Groq call with rate-limit backoff (gpt-oss-120b is capped at 8k tokens/min)."""
    for attempt in range(6):
        try:
            return client.chat.completions.create(
                model=MODEL, messages=messages, tools=tools.TOOL_DEFS,
                tool_choice="auto", temperature=0)
        except RateLimitError as e:
            wait = parse_retry_seconds(str(e), default=6.0)
            if attempt == 5:
                raise
            time.sleep(wait + 0.5)


def run(query, max_iters=MAX_ITERS, system=SYSTEM):
    client = get_client()
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": query}]
    trace = {"query": query, "steps": [], "tools_used": []}

    for _ in range(max_iters):
        resp = _create(client, messages)
        msg = resp.choices[0].message

        if not msg.tool_calls:                       # model chose to answer directly
            trace["steps"].append({"type": "final_answer"})
            return msg.content, trace

        # record the assistant turn (with its tool_calls) before adding tool results
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})

        for tc in msg.tool_calls:
            name = tc.function.name
            # 1) parse arguments (a malformed JSON string is itself an invalid call)
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args, parse_ok = {}, False
            else:
                parse_ok = True

            # 2) validate against the strict schema (the safety gate)
            if not parse_ok:
                ok, reason, clean = False, "arguments were not valid JSON", None
            else:
                ok, reason, clean = tools.validate_args(name, args)

            if not ok:
                result = {"error": f"rejected: {reason}"}
                trace["steps"].append({"type": "tool_rejected", "tool": name,
                                       "args": args, "reason": reason})
            else:
                result = tools.TOOL_FUNCS[name](**clean)
                trace["steps"].append({"type": "tool_call", "tool": name,
                                       "args": clean})
                trace["tools_used"].append(name)

            # 3) feed the (result OR rejection) back to the model
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "name": name, "content": json.dumps(result)[:1800]})

    # safety valve: too many tool rounds
    trace["steps"].append({"type": "max_iters_reached"})
    return "I couldn't complete that request within the allowed steps.", trace


if __name__ == "__main__":
    for q in ["What cheap art is in Berlin?",
              "Budget for 4 days, 2 people, 75/day food, 40/day activities, 60 pass each?",
              "Hello, what can you do?"]:
        ans, tr = run(q)
        used = tr["tools_used"] or ["(none)"]
        print(f"\nQ: {q}\n  tools: {used}\n  answer: {ans[:160]}")
