"""
Week 3 - Day 1 - skip-probe: does the model skip the calculator, and does that cost
correctness? Runs multi-step budget questions under the NEUTRAL prompt (tools
optional) vs the STRONG prompt (use the tool), and checks each answer against the
EXACT value from estimate_trip_budget. This produces:
  * "should-have-used-but-didn't" cases (neutral prompt skips the tool), and
  * evidence for concept 4 (a skipped tool -> a wrong number the tool would have fixed).
"""

import json
import re
import time
from pathlib import Path

import agent
import tools

DAY_DIR = Path(__file__).parent

# each: question + the exact total (computed by the deterministic tool)
CASES = [
    {"q": "Trip: 3 days, 2 people, 65/day food, 35/day activities, 55 euro pass each. Total?",
     "exact": tools.estimate_trip_budget(3, 2, 65, 35, 55)["total_eur"]},
    {"q": "7 days, 4 people, 42/day food, 28/day activities, no pass. Total cost?",
     "exact": tools.estimate_trip_budget(7, 4, 42, 28, 0)["total_eur"]},
    {"q": "5 days for 3 travelers, 38 food and 47 activities per day each, plus a 29 euro pass each. Total?",
     "exact": tools.estimate_trip_budget(5, 3, 38, 47, 29)["total_eur"]},
    {"q": "2 people, 6 days, 55/day food, 45/day activities, 80 pass each — total budget?",
     "exact": tools.estimate_trip_budget(6, 2, 55, 45, 80)["total_eur"]},
    {"q": "A 4-day trip for 3 people at 33/day food and 27/day activities each. Total?",
     "exact": tools.estimate_trip_budget(4, 3, 33, 27, 0)["total_eur"]},
]


def has_number(text, value):
    """Is the exact total present in the answer (with/without thousands separators)?"""
    v = int(value) if float(value).is_integer() else value
    variants = {str(v), f"{v:,}", f"{v:.2f}", f"€{v}", f"{v} euro"}
    low = text.replace(",", "")
    return any(str(v).replace(",", "") in low for _ in [0]) or any(x in text for x in variants)


def main():
    rows = []
    for c in CASES:
        for label, system in [("neutral", agent.SYSTEM_NEUTRAL), ("strong", agent.SYSTEM)]:
            ans, tr = agent.run(c["q"], system=system)
            used = bool(tr["tools_used"])
            correct = has_number(ans, c["exact"])
            rows.append({"q": c["q"], "exact": c["exact"], "prompt": label,
                         "used_tool": used, "answer": ans})
            print(f"[{label:<7}] tool={'Y' if used else 'N'} correct={'Y' if correct else 'N'} "
                  f"exact={c['exact']}  {c['q'][:46]}")
            time.sleep(7)
    (DAY_DIR / "skip_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'skip_results.json'}")


if __name__ == "__main__":
    main()
