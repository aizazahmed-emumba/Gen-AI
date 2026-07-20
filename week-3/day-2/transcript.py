"""
Week 3 - Day 2 - generate a human-readable TRANSCRIPT of the agent's turns.

For each turn it records: the memory going in, the user message, every ReAct step
(what the LLM DECIDED + its reason + args, what we VALIDATED, what we OBSERVED),
the final answer, and the updated memory. Output -> transcript.md
"""

import time
from pathlib import Path

import agent_loop
import memory

DAY_DIR = Path(__file__).parent

CONVERSATIONS = [
    {"id": "C1 — coreference (memory HELPS)", "verdict": "✅ correct",
     "turns": ["I'm planning a 3-day trip to Berlin. What cheap art can I see?",
               "And where can I eat cheaply there?"]},
    {"id": "C2 — context carry (memory HELPS)", "verdict": "✅ correct",
     "turns": ["What's the budget for 4 days, 2 people, 75 food and 40 activities per day?",
               "What if we each also buy a 60 euro museum pass?"]},
    {"id": "C3 — refuse (memory HELPS, no override)", "verdict": "✅ correct",
     "turns": ["Show me museums in Amsterdam.",
               "What about Tokyo - any good museums there?"]},
    {"id": "C4 — category bleed (memory HURTS)", "verdict": "❌ wrong on turn 2",
     "turns": ["I only care about art - show me art in Paris.",
               "What else is worth seeing while I'm there?"]},
    {"id": "C5 — price bleed (memory HURTS)", "verdict": "❌ wrong on turn 3",
     "turns": ["Show me cheap art in Berlin.",
               "Hmm, I'm now thinking about Paris instead.",
               "What are the best museums there?"]},
]


def render_step(i, s):
    line = [f"{i}. 🤔 **DECIDE** → `{s['action']}`"]
    if s.get("reason"):
        line.append(f"   \n   *reason:* {s['reason']}")
    if s.get("args"):
        line.append(f"   \n   *args:* `{s['args']}`")
    if s.get("rejected"):
        line.append(f"   \n   ⛔ *validator REJECTED:* {s['rejected']} → fed back as an observation (self-correction)")
    elif s.get("observed_detail"):
        line.append(f"   \n   ✅ *validated → EXECUTED → OBSERVED:* " + "; ".join(s["observed_detail"]))
    if s.get("final"):
        line.append(f"   \n   🏁 *ends the loop with `{s['final']}`*")
    return "\n".join(line)


def main():
    md = ["# Day 12 — Agent Transcript (memory · context · reasoning · reply · action)\n",
          "Each turn shows: **memory in** → the user message → the agent's **ReAct steps** "
          "(what the LLM decided, its reason, what we validated/observed) → the **final answer** "
          "→ the **updated memory**.\n"]

    for conv in CONVERSATIONS:
        md.append(f"\n---\n\n## {conv['id']} — {conv['verdict']}\n")
        mem = ""
        for t, user in enumerate(conv["turns"], 1):
            answer, steps = agent_loop.run_turn(user, mem)
            md.append(f"### Turn {t}\n")
            md.append(f"- **🧠 Memory in:** {mem or '_(empty — first turn)_'}")
            md.append(f"- **👤 User:** {user}")
            md.append("- **⚙️ Agent reasoning (ReAct loop):**\n")
            for i, s in enumerate(steps, 1):
                md.append(render_step(i, s) + "\n")
            md.append(f"- **💬 Final answer (LLM reply):** {answer.strip()[:600]}")
            new_mem = memory.update(mem, user, answer)
            md.append(f"- **🧠 Memory out:** {new_mem}\n")
            mem = new_mem
            time.sleep(6)

    (DAY_DIR / "transcript.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Saved -> {DAY_DIR / 'transcript.md'}")


if __name__ == "__main__":
    main()
