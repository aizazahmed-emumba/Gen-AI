"""
Week 2 - Day 4 (Course Day 9) - Prompts, JSON schema, and the validation gate.

This file holds the two GENERATION STRATEGIES we compare, the target schema, and
the validator that decides whether an output is accepted or rejected.

CONCEPT — prompt strategies for grounded answers
-------------------------------------------------
Both prompts ask for the SAME JSON ({answer, citations, confidence}); they differ
only in how hard they push the model to STAY GROUNDED in the passages:

  FREE_FORM        "here's the question and some context, answer it as JSON."
                   No insistence on using only the context, no citation duty, no
                   abstention rule. The model happily answers from its own
                   parametric memory and is over-confident -> this is where
                   hallucinations live, and where generation AMPLIFIES retrieval
                   errors (bad context in -> confident wrong answer out).

  CITATION_ENFORCED "answer ONLY from the numbered passages; cite the passage
                   number behind every claim; if it isn't there, say NOT IN
                   CONTEXT and drop your confidence." Grounding is now a hard
                   instruction, so wrong/missing context tends to produce an
                   abstention instead of a confident fabrication.

CONCEPT — structured generation + required vs optional fields
-------------------------------------------------------------
Asking for JSON in a prompt does NOT guarantee schema-valid data — even Groq's
JSON mode only guarantees the output PARSES, not that it has the right fields and
types. So we validate ourselves. REQUIRED fields (answer, confidence) missing =>
reject. OPTIONAL fields (citations) may be absent (an abstention legitimately
cites nothing). Validation is the QUALITY GATE: nothing reaches a downstream
system unless it conforms.
"""

# The schema we require. answer + confidence are REQUIRED; citations is OPTIONAL.
SCHEMA_DOC = """{
  "answer": string,               // REQUIRED, non-empty
  "citations": [integer, ...],    // OPTIONAL, each must be a passage number shown below
  "confidence": number            // REQUIRED, between 0.0 and 1.0
}"""


FREE_FORM = """Question: {question}

Some possibly-relevant context:
{passages}

Give your answer as a JSON object with keys "answer", "citations", "confidence"."""


CITATION_ENFORCED = """You answer strictly from the numbered passages below. Rules:
- Use ONLY information found in the passages. Do not use outside knowledge.
- Every factual claim in "answer" must be backed by the passage number(s) it came from, listed in "citations".
- If the passages do not contain the answer, set "answer" to "NOT IN CONTEXT", "citations" to [], and "confidence" to a low value.
- "confidence" is your calibrated probability (0.0-1.0) that the answer is correct and supported.

Return ONLY a JSON object matching this schema (no prose, no markdown fences):
{schema}

Question: {question}

Passages:
{passages}"""


def build(prompt_template, question, passages_text, **extra):
    return prompt_template.format(question=question, passages=passages_text, **extra)


# ─────────────────────────────────────────────────────────────────────────────
# THE VALIDATION GATE
# ─────────────────────────────────────────────────────────────────────────────

import json


def validate(raw_text, num_passages):
    """Return (ok, reason, parsed). `ok=False` means REJECT; `reason` says why.
    Checks two layers: (1) does it parse as JSON, (2) does it match the schema."""
    # Layer 1 — syntactic: must parse as a JSON object.
    try:
        obj = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        hint = ""
        if "```" in raw_text:
            hint = " (wrapped in a markdown ``` fence)"
        elif raw_text.strip()[:1] not in "{[":
            hint = " (leading prose before the JSON)"
        return False, f"invalid JSON syntax{hint}", None
    if not isinstance(obj, dict):
        return False, "top-level JSON is not an object", None

    # Layer 2 — schema: required fields, types, and semantic ranges.
    if "answer" not in obj:
        return False, "missing required field 'answer'", None
    if not isinstance(obj["answer"], str) or not obj["answer"].strip():
        return False, "'answer' must be a non-empty string", None

    if "confidence" not in obj:
        return False, "missing required field 'confidence'", None
    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return False, f"'confidence' must be a number, got {type(conf).__name__}", None
    if not (0.0 <= conf <= 1.0):
        return False, f"'confidence' {conf} out of range [0,1]", None

    # citations is OPTIONAL, but if present must be a list of in-range passage ints.
    cites = obj.get("citations", [])
    if not isinstance(cites, list):
        return False, "'citations' must be a list", None
    for c in cites:
        if isinstance(c, bool) or not isinstance(c, int):
            return False, f"citation {c!r} is not an integer", None
        if not (1 <= c <= num_passages):
            return False, f"citation {c} out of range 1..{num_passages}", None

    return True, "ok", obj
