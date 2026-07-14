"""
Week 2 - Day 4 (Course Day 9) - Answer generators.

Three answering modes, to make CONCEPT 1 (extractive vs generative) concrete:

  extractive  — no LLM. Return the single passage SENTENCE that best lexically
                matches the question, verbatim. It literally cannot hallucinate
                (it only copies text that's in the corpus) — but it also can't
                synthesize, rephrase, or answer a compound/2-fact question. This
                is the safety/■fluency trade-off in its purest form.

  free_form / citation_enforced — generative. The LLM writes new text, so it can
                synthesize and read naturally, but it CAN invent facts. The two
                prompts differ only in grounding pressure (see prompts.py).

Generative outputs are cached to gen_cache.json so re-runs are free/deterministic.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import ask

import prompts

DAY_DIR = Path(__file__).parent
CACHE = DAY_DIR / "gen_cache.json"
MODEL = "openai/gpt-oss-120b"

_cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
_WORD = re.compile(r"[a-z0-9]+")


# ─────────────────────────────────────────────────────────────────────────────
# Extractive (no LLM) — copies a real span
# ─────────────────────────────────────────────────────────────────────────────

def extractive_answer(question, passages):
    q_terms = set(_WORD.findall(question.lower()))
    best, best_score, best_n = "", -1, None
    for p in passages:
        for sent in re.split(r"(?<=[.!?])\s+", p["text"]):
            terms = set(_WORD.findall(sent.lower()))
            overlap = len(q_terms & terms)
            if overlap > best_score and len(sent.split()) >= 3:
                best, best_score, best_n = sent.strip(), overlap, p["n"]
    # confidence = fraction of question terms the chosen sentence covers
    conf = round(best_score / max(len(q_terms), 1), 2)
    return {"answer": best or "NOT IN CONTEXT",
            "citations": [best_n] if best_n else [],
            "confidence": conf}


# ─────────────────────────────────────────────────────────────────────────────
# Generative (LLM) — returns the RAW text so the validator can judge it
# ─────────────────────────────────────────────────────────────────────────────

def generate_raw(prompt_name, question, passages):
    key = f"{prompt_name}::{question}"
    if key in _cache:
        return _cache[key]

    passages_text = prompts.build_passages(passages) if hasattr(prompts, "build_passages") else \
        "\n\n".join(f"[{p['n']}] ({p['source']}) {p['text']}" for p in passages)

    if prompt_name == "free_form":
        # No JSON mode: we ask for JSON in plain text, so some outputs will be
        # malformed — that's deliberate, to exercise the validation gate.
        prompt = prompts.build(prompts.FREE_FORM, question, passages_text)
        raw = ask(prompt, model=MODEL, temperature=0.7)
    elif prompt_name == "citation_enforced":
        # JSON mode ON + explicit schema -> syntactically valid, mostly on-schema.
        prompt = prompts.build(prompts.CITATION_ENFORCED, question, passages_text,
                               schema=prompts.SCHEMA_DOC)
        raw = ask(prompt, model=MODEL, temperature=0.0,
                  response_format={"type": "json_object"})
    else:
        raise ValueError(prompt_name)

    _cache[key] = raw
    CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2))
    return raw
