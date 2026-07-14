"""
Week 2 - Day 4 (Course Day 9) - RUN both generation strategies + validate.

For each question (same fixed top-5 context):
  1. extractive baseline (no LLM, always schema-valid by construction)
  2. free_form prompt        -> validate -> accept / reject+reason
  3. citation_enforced prompt -> validate -> accept / reject+reason
Everything (raw output, validity, reject reason, parsed object) is saved for
scoring.
"""

import json
from pathlib import Path

import context
import answergen as generate
import prompts

DAY_DIR = Path(__file__).parent


def main():
    ctx = context.build_contexts()
    test = json.loads((DAY_DIR.parent / "day-3" / "test_set.json").read_text())
    print(f"Running {len(test)} questions x 2 prompts...\n")

    results = []
    for item in test:
        qid = item["id"]
        passages = ctx[qid]
        n = len(passages)
        row = {"id": qid, "category": item["category"], "question": item["question"],
               "modes": {}}

        # extractive (constructed valid)
        ext = generate.extractive_answer(item["question"], passages)
        row["modes"]["extractive"] = {"raw": json.dumps(ext), "valid": True,
                                      "reason": "ok", "parsed": ext}

        # two generative prompts, each passed through the validation gate
        for name in ("free_form", "citation_enforced"):
            raw = generate.generate_raw(name, item["question"], passages)
            ok, reason, parsed = prompts.validate(raw, n)
            row["modes"][name] = {"raw": raw, "valid": ok, "reason": reason, "parsed": parsed}

        results.append(row)
        ff = "ok" if row["modes"]["free_form"]["valid"] else "REJECT"
        ce = "ok" if row["modes"]["citation_enforced"]["valid"] else "REJECT"
        print(f"{qid:<4} [{item['category']:<11}] free_form={ff:<6} citation_enforced={ce}")

    (DAY_DIR / "run_results.json").write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2))
    print(f"\nSaved -> {DAY_DIR / 'run_results.json'}")


if __name__ == "__main__":
    main()
