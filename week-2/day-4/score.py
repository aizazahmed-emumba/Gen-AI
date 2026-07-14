"""
Week 2 - Day 4 (Course Day 9) - SCORE and analyze.

Tables:
  1. answer correctness   — is the fact right? (answerable: gold phrase in answer;
                            trap: did it correctly ABSTAIN?)
  2. citation presence    — did the output include at least one citation?
  3. JSON validity pass rate — did it survive the validation gate?

Correctness is measured on a LENIENT parse of the answer text, even for outputs
the gate rejected — so we can separate two different questions: "was the content
right?" (correctness) vs "was the output usable?" (validity). A free-form answer
can be factually right yet structurally unusable; that gap is the whole point.
"""

import json
import re
from pathlib import Path

DAY_DIR = Path(__file__).parent
MODES = ["extractive", "free_form", "citation_enforced"]
_ANS = re.compile(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"')
_CITES = re.compile(r'"citations"\s*:\s*\[([^\]]*)\]')


def lenient_answer(raw):
    try:
        o = json.loads(raw)
        if isinstance(o, dict) and isinstance(o.get("answer"), str):
            return o["answer"]
    except Exception:
        pass
    m = _ANS.search(raw)
    return m.group(1) if m else raw


def has_citation(raw):
    try:
        o = json.loads(raw)
        if isinstance(o, dict):
            return bool(o.get("citations"))
    except Exception:
        pass
    m = _CITES.search(raw)
    return bool(m and m.group(1).strip())


def is_abstain(ans):
    return "not in context" in ans.lower()


def correct(item, ans):
    if item["category"] == "trap":
        return is_abstain(ans)
    if is_abstain(ans):
        return False
    if item["category"] == "compound":
        return all(any(p.lower() in ans.lower() for p in sub["gold_phrases"])
                   for sub in item["sub_questions"])
    return any(p.lower() in ans.lower() for p in item["gold_phrases"])


def main():
    test = {it["id"]: it for it in json.loads((DAY_DIR.parent / "day-3" / "test_set.json").read_text())}
    run = json.loads((DAY_DIR / "run_results.json").read_text())["results"]
    n = len(run)

    corr = {m: 0 for m in MODES}
    cite = {m: 0 for m in MODES}
    valid = {m: 0 for m in MODES}
    for r in run:
        it = test[r["id"]]
        for m in MODES:
            raw = r["modes"][m]["raw"]
            if correct(it, lenient_answer(raw)):
                corr[m] += 1
            if has_citation(raw):
                cite[m] += 1
            if r["modes"][m]["valid"]:
                valid[m] += 1

    print(f"\n=== Comparison ({n} questions) ===")
    print(f"  {'metric':<24}" + "".join(f"{m:>20}" for m in MODES))
    print(f"  {'answer correctness':<24}" + "".join(f"{corr[m]:>13}/{n} {corr[m]/n:>4.0%}" for m in MODES))
    print(f"  {'citation presence':<24}" + "".join(f"{cite[m]:>13}/{n} {cite[m]/n:>4.0%}" for m in MODES))
    print(f"  {'JSON validity pass rate':<24}" + "".join(f"{valid[m]:>13}/{n} {valid[m]/n:>4.0%}" for m in MODES))

    # ---- Hallucination analysis ----
    print("\n=== Hallucinations (free_form): confident answer not grounded / trap answered ===")
    halluc = []
    for r in run:
        it = test[r["id"]]
        ans = lenient_answer(r["modes"]["free_form"]["raw"])
        if it["category"] == "trap" and not is_abstain(ans):
            halluc.append((r["id"], "answered a trap (no such info in corpus)", ans[:70]))
        elif it["category"] != "trap":
            # answered confidently but citation-enforced (grounded) abstained -> ungrounded/parametric
            ce = lenient_answer(r["modes"]["citation_enforced"]["raw"])
            if not is_abstain(ans) and is_abstain(ce):
                halluc.append((r["id"], "answered from memory; not supported by retrieved context", ans[:70]))
    for h in halluc:
        print(f"  {h[0]:<4} {h[1]:<58} | {h[2]}")

    # ---- Invalid-output log ----
    print("\n=== Rejected outputs (validation gate) ===")
    for r in run:
        for m in ["free_form", "citation_enforced"]:
            if not r["modes"][m]["valid"]:
                print(f"  {r['id']:<4} {m:<18} {r['modes'][m]['reason']}")

    (DAY_DIR / "scoring_results.json").write_text(json.dumps(
        {"correct": corr, "cite": cite, "valid": valid, "n": n,
         "hallucinations": halluc}, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'scoring_results.json'}")


if __name__ == "__main__":
    main()
