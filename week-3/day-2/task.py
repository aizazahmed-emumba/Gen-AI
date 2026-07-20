"""
Week 3 - Day 2 (Course Day 12) - multi-turn test harness.

Runs 5 conversations turn-by-turn. Between turns we carry ONLY the rolling
short-term summary (memory.update) — not the full transcript — so we can watch
memory help (coreference / carrying context) and hurt (stale city / preference
bleed). Each turn logs: the memory going in, the agent's decisions, the answer,
and the memory coming out.
"""

import json
import time
from pathlib import Path

import agent_loop
import memory

DAY_DIR = Path(__file__).parent

CONVERSATIONS = [
    {"id": "C1-coref", "note": "memory HELPS: 'there' resolves to Berlin",
     "turns": ["I'm planning a 3-day trip to Berlin. What cheap art can I see?",
               "And where can I eat cheaply there?",
               "Roughly how much for 3 days at 60 a day for food and 30 for activities, just me?"]},

    {"id": "C2-budget-carry", "note": "memory HELPS: carries days/travelers/rates into a follow-up",
     "turns": ["What's the budget for 4 days, 2 people, 75 food and 40 activities per day?",
               "What if we each also buy a 60 euro museum pass?"]},

    {"id": "C3-refuse", "note": "memory HELPS (doesn't override): refuse unsupported city",
     "turns": ["Show me museums in Amsterdam.",
               "What about Tokyo — any good museums there?"]},

    {"id": "C4-stale-city", "note": "memory HURTS: user switches to Paris, stale summary keeps Berlin",
     "turns": ["Show me cheap art in Berlin.",
               "Hmm, I'm now thinking about Paris instead.",
               "What are the best museums there?"]},

    {"id": "C5-pref-bleed", "note": "memory HURTS: 'cheap' bleeds into an anniversary splurge",
     "turns": ["Find me cheap food in Rome.",
               "Actually it's for my anniversary - suggest somewhere really special and upscale for dinner."]},
]


def main():
    out = []
    for conv in CONVERSATIONS:
        mem = ""
        turns_log = []
        print(f"\n=== {conv['id']} — {conv['note']} ===")
        for user in conv["turns"]:
            answer, steps = agent_loop.run_turn(user, mem)
            actions = " -> ".join(s["action"] for s in steps)
            retrieved = next((s.get("args") for s in steps if s["action"] == "retrieve"), None)
            turns_log.append({"user": user, "memory_in": mem, "actions": actions,
                              "retrieve_args": retrieved, "answer": answer})
            print(f"  U: {user[:60]}")
            print(f"     mem_in: {mem[:80] or '(empty)'}")
            print(f"     actions: {actions}   retrieve={retrieved}")
            mem = memory.update(mem, user, answer)
            time.sleep(6)
        out.append({**conv, "turns_log": turns_log})

    (DAY_DIR / "run_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'run_results.json'}")


if __name__ == "__main__":
    main()
