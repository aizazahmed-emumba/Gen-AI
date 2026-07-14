# Week 2 – Day 4 Report (Course Day 9) — Answer Generation & Structured Output Enforcement

## Task

Hold retrieval **fixed** (Day-8 weighted-hybrid top-5, identical for every mode) and vary only the **answer-generation strategy**. Compare a free-form prompt vs a citation-enforced prompt, both targeting a structured JSON object `{answer, citations, confidence}`, validate every output against a schema, and reject + log the failures.

Model: `gpt-oss-120b`. 23 questions (21 answerable + 2 traps). Code: [prompts.py](week-2/day-4/prompts.py) (prompts + schema + validator), [answergen.py](week-2/day-4/answergen.py) (extractive + 2 generative modes), [context.py](week-2/day-4/context.py), [task.py](week-2/day-4/task.py), [score.py](week-2/day-4/score.py).

Three modes (the third, **extractive**, is added to make *extractive vs generative* concrete):

| Mode | How | Can it hallucinate? |
| --- | --- | --- |
| **extractive** | no LLM — copies the passage sentence that best lexically matches the question | **No** (only copies real text) |
| **free_form** | LLM, loose prompt, asks for JSON in plain text | Yes |
| **citation_enforced** | LLM, strict "answer only from passages + cite + abstain" prompt, JSON mode | Yes, but suppressed |

## Results — the comparison table

| metric | extractive | free_form | citation_enforced |
| --- | --- | --- | --- |
| **answer correctness** | 9/23 (39%) | **18/23 (78%)** | 14/23 (61%) |
| **citation presence** | 23/23 (100%) | 20/23 (87%) | 15/23 (65%) |
| **JSON validity pass rate** | 23/23 (100%) | **2/23 (9%)** | **22/23 (96%)** |

**The headline is a trap, and spotting the trap is the lesson.** free_form has the *highest* correctness (78%) and the *lowest* validity (9%). Read naively, "free-form is most accurate." Read correctly: **free-form is right about the content and useless as output** — 91% of its answers can't be parsed by a downstream system, and its "accuracy" comes from answering out of the model's memory rather than the retrieved context (see hallucinations below). Correctness measured on answer text alone is a misleading metric; you need validity *and* grounding beside it.

## Concept walk-through, grounded in this run

**1. Extractive vs generative.** Extractive scored lowest (39%) but is the safety floor: it *never* fabricates and is *always* structured, because it just returns real spans. It fails when the answer must be synthesized, rephrased, or combines two facts (compound questions) — it can only hand back one existing sentence. Generative modes read naturally and synthesize, at the cost of being *able* to invent. This is the core trade-off: **extractive trades capability for safety; generative trades safety for capability.**

**2. Prompt strategies for grounded answers.** The only difference between free_form and citation_enforced is grounding pressure. citation_enforced's rules — *use only the passages, cite every claim, say NOT IN CONTEXT if it's absent* — changed behaviour dramatically: it **abstained** on the 5 questions where retrieval had missed (Q4, Q6, Q7, Q17, Q21) instead of answering from memory. That's why its correctness looks *lower* (61%): most of its "misses" are honest abstentions on questions the context genuinely didn't support — the correct, trustworthy behaviour for a RAG system.

**3. Why generation amplifies retrieval errors (the clearest demo).** free_form answered from parametric memory regardless of context:

| Q | retrieval status | free_form | citation_enforced |
| --- | --- | --- | --- |
| Q19 (trap: capital of France) | not in corpus | **"Paris"** | NOT IN CONTEXT |
| Q20 (trap: Kubernetes ingress) | not in corpus | **wrote a full how-to** | NOT IN CONTEXT |
| Q4 / Q17 (Ishmael) | retrieval missed | confident correct-sounding answer | NOT IN CONTEXT |
| Q21 (AC-11) | retrieval missed | detailed control description | NOT IN CONTEXT |

The danger isn't that "Paris" is wrong — it's *right*, but it's **ungrounded**: the system asserts facts its sources don't contain. On a question where the model's memory is *wrong*, free_form would state the wrong answer with the exact same fluency and confidence (0.99). Generation doesn't fix a bad/empty retrieval — it **papers over it** with confident prose. Grounding + abstention is the only defense.

**4. Structured generation with JSON schemas.** Asking for JSON in prose (free_form) yielded **9%** valid output; an explicit schema + JSON mode (citation_enforced) yielded **96%**. JSON mode guarantees the text *parses* — but note it did **not** guarantee schema conformance: citation_enforced's one failure (Q3) was perfectly-formed JSON citing passage `[1234]`, which doesn't exist. Syntactic validity ≠ semantic validity.

**5. Required vs optional fields + validation as a quality gate.** The validator ([prompts.py](week-2/day-4/prompts.py) `validate`) treats `answer` and `confidence` as **required**, `citations` as **optional** (an abstention legitimately cites nothing). It checks two layers — does it parse, and does it match the schema (types + citation ranges + confidence ∈ [0,1]). This gate rejected 22 outputs that a naive `json.loads` would either have crashed on or silently accepted with garbage fields.

## Analysis — 5 hallucination examples & why

| # | Q | free_form answer | why it happened |
| --- | --- | --- | --- |
| 1 | Q19 (trap) | "Paris" | trap has no support in the corpus; loose prompt has no abstention rule, so the model answered from world knowledge — **ungrounded fact** |
| 2 | Q20 (trap) | full Kubernetes how-to guide | same: no grounding/abstention rule → the model happily generated a long confident answer for something entirely outside the corpus |
| 3 | Q4 (Ishmael) | "narrated by a sailor named Ishmael… 'Call me Ishmael'" | retrieval **missed** the opening chunk (Day-7 semantic-gap wall); free_form filled the gap from memory, hiding the retrieval failure |
| 4 | Q21 (AC-11) | detailed "Device Lock" requirements | AC-11 wasn't in the top-5; the model reconstructed it from training data — plausible, confident, unverifiable against the provided context |
| 5 | Q23 (AC-6) | full least-privilege explanation | context was thin; model padded with parametric knowledge → an answer that reads authoritative but isn't traceable to a cited passage |

Common thread: **every hallucination is the model substituting its own memory for absent/weak retrieved context.** citation_enforced abstained on all five; free_form fabricated on all five.

## Analysis — 5 invalid outputs & failure reason

| # | Q | mode | reason | root cause |
| --- | --- | --- | --- | --- |
| 1 | Q1 | free_form | `citations` was a list of **objects** `{"source":"[1]","text":"…"}`, not integers | loose prompt never pinned the citation *type*; model chose a rich, human-looking format that breaks the schema |
| 2 | Q4 | free_form | `confidence` was a **string** ("0.99"/"high"), not a number | no type discipline in the prompt → the field parses but is the wrong type |
| 3 | Q6 | free_form | **invalid JSON syntax** | model wrapped output in prose / markdown, so it didn't parse at all |
| 4 | Q7 | free_form | `citations` was a **bibliographic string** ("Melville, Herman. *Moby-Dick*…") | model interpreted "citation" as an academic reference, not a passage index |
| 5 | **Q3** | **citation_enforced** | citation **`[1234]` out of range 1..5** | JSON was syntactically perfect; only **semantic** validation caught a hallucinated passage number — the case JSON mode can't protect you from |

Failure classes seen: wrong container type (objects/strings for citations), wrong scalar type (confidence as string), unparseable JSON, and out-of-range references. Only the last survives JSON mode — which is exactly why you validate the *schema*, not just the syntax.

## Conclusions

1. **Don't rank generation strategies on correctness alone.** free_form "won" correctness (78%) while being 91% unusable and hallucinating on 100% of traps. A production metric must combine correctness **+ grounding + validity**.
2. **Grounding prompts trade apparent coverage for trust.** citation_enforced's lower correctness (61%) is mostly honest abstentions; it fabricated nothing and stayed 96% valid — the shippable choice.
3. **Structured output needs two gates.** JSON mode buys syntactic validity (9% → 96%); a schema validator buys *semantic* validity (types, required fields, in-range citations) — the Q3 `[1234]` case proves the second is not optional.
4. **Extractive is the hallucination-proof floor**, useful when a wrong answer is costlier than no answer — at the price of never synthesizing.

**Next-day candidates:** (a) feed the `confidence` field into an abstention threshold (auto-reject low-confidence answers); (b) add a "supported-by-citation" check that verifies each claim's cited passage actually contains it (self-grounding audit); (c) retry rejected outputs by feeding the validator's error back to the model (self-repair loop).
