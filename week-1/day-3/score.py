import json
import re
from pathlib import Path
from collections import Counter

DAY3_DIR = Path(__file__).parent

REFUSAL_PATTERNS = [
    "not in document", "not in the document", "not found", "not stated",
    "not specified", "no information", "not mentioned", "cannot be determined",
    "does not state", "does not specify", "does not mention", "not available",
    "not provided", "doesn't state", "doesn't specify", "doesn't mention",
    "not given", "unable to determine", "no mention",
]

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text.lower())


def abstained(answer):
    lower = normalize_whitespace(answer)
    return any(p in lower for p in REFUSAL_PATTERNS)


def fact_match(answer, key_terms):
    lower = normalize_whitespace(answer)
    return any(normalize_whitespace(term) in lower for term in key_terms)


def token_f1(answer, reference):
    pred_tokens = tokenize(answer)
    ref_tokens = tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred_counts = Counter(pred_tokens)
    ref_counts = Counter(ref_tokens)
    overlap = sum((pred_counts & ref_counts).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def groundedness(answer, context):
    answer_tokens = set(tokenize(answer))
    context_tokens = set(tokenize(context))
    if not answer_tokens:
        return None
    grounded = answer_tokens & context_tokens
    return len(grounded) / len(answer_tokens)


def score_model(results, test_by_id, model_key):
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]

    fact_matches, f1_scores, ground_scores = [], [], []
    per_question = {}

    for r in answerable:
        item = test_by_id[r["id"]]
        answer = r[f"{model_key}_answer"]
        key_terms = item["key_terms"]
        matched = fact_match(answer, key_terms)
        f1 = token_f1(answer, key_terms[0])
        fact_matches.append(matched)
        f1_scores.append(f1)

        did_abstain = abstained(answer)
        if not did_abstain:
            g = groundedness(answer, r["retrieved_context"])
            if g is not None:
                ground_scores.append(g)

        per_question[r["id"]] = {
            "answerable": True,
            "passed": matched,
            "abstained": did_abstain,
            "f1": round(f1, 3),
        }

    abstain_correct = []
    for r in unanswerable:
        answer = r[f"{model_key}_answer"]
        did_abstain = abstained(answer)
        abstain_correct.append(did_abstain)
        per_question[r["id"]] = {
            "answerable": False,
            "passed": did_abstain,
            "abstained": did_abstain,
            "f1": None,
        }

    n_total = len(results)
    n_passed = sum(1 for v in per_question.values() if v["passed"])

    metrics = {
        "exact_fact_match_rate": round(sum(fact_matches) / len(fact_matches), 3) if fact_matches else None,
        "token_f1": round(sum(f1_scores) / len(f1_scores), 3) if f1_scores else None,
        "abstention_accuracy": round(sum(abstain_correct) / len(abstain_correct), 3) if abstain_correct else None,
        "groundedness": round(sum(ground_scores) / len(ground_scores), 3) if ground_scores else None,
    }

    pass_fail = {
        "passed": n_passed,
        "total": n_total,
        "pass_rate": round(n_passed / n_total, 3),
    }

    return metrics, pass_fail, per_question


def context_had_answer(context, key_terms):
    lower = normalize_whitespace(context)
    return any(normalize_whitespace(term) in lower for term in key_terms)


def build_failures(results, test_by_id, per_question_a, per_question_b):
    failures = []
    for r in results:
        item = test_by_id[r["id"]]
        for model_key, model_name, per_q in [
            ("model_a", r["model_a"], per_question_a),
            ("model_b", r["model_b"], per_question_b),
        ]:
            record = per_q[r["id"]]
            if record["passed"]:
                continue
            answer = r[f"{model_key}_answer"]
            if r["answerable"]:
                had_answer = context_had_answer(r["retrieved_context"], item["key_terms"])
                reason = (
                    f"Model failed despite the correct fact being present in its retrieved context "
                    f"(expected: {item['expected_answer']})"
                    if had_answer else
                    f"Retrieval didn't surface the source page, so the model had no way to know "
                    f"(expected: {item['expected_answer']})"
                )
            else:
                reason = "Model fabricated an answer instead of recognizing the fact isn't in either document"
            failures.append({
                "id": r["id"],
                "model": model_name,
                "question": r["question"],
                "answer": answer.strip()[:200],
                "reason": reason,
                "retrieval_at_fault": r["answerable"] and not context_had_answer(r["retrieved_context"], item["key_terms"]),
            })
    return failures


def main():
    test_set = json.loads((DAY3_DIR / "test_set.json").read_text(encoding="utf-8"))
    test_by_id = {t["id"]: t for t in test_set}
    results = json.loads((DAY3_DIR / "run_results.json").read_text(encoding="utf-8"))

    metrics_a, pass_fail_a, per_q_a = score_model(results, test_by_id, "model_a")
    metrics_b, pass_fail_b, per_q_b = score_model(results, test_by_id, "model_b")

    failures = build_failures(results, test_by_id, per_q_a, per_q_b)

    model_a_name = results[0]["model_a"]
    model_b_name = results[0]["model_b"]

    print(f"\n{'Metric':<28}{model_a_name:<28}{model_b_name}")
    print("-" * 80)
    for key in metrics_a:
        print(f"{key:<28}{str(metrics_a[key]):<28}{str(metrics_b[key])}")

    print(f"\nPass/Fail — {model_a_name}: {pass_fail_a['passed']}/{pass_fail_a['total']} ({pass_fail_a['pass_rate']:.0%})")
    print(f"Pass/Fail — {model_b_name}: {pass_fail_b['passed']}/{pass_fail_b['total']} ({pass_fail_b['pass_rate']:.0%})")

    print(f"\nTotal failures logged: {len(failures)}")
    for f in failures:
        print(f"  [{f['id']}] {f['model']} — {f['reason']}")

    output = {
        "model_a": model_a_name,
        "model_b": model_b_name,
        "metrics": {"model_a": metrics_a, "model_b": metrics_b},
        "pass_fail": {"model_a": pass_fail_a, "model_b": pass_fail_b},
        "per_question": {"model_a": per_q_a, "model_b": per_q_b},
        "failures": failures,
    }
    out_path = DAY3_DIR / "scoring_results.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved scoring results to {out_path}")


if __name__ == "__main__":
    main()
