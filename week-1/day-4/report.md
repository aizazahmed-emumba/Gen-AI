# Week 1 – Day 4 Report

## Task

Build a RAG pipeline from scratch (embeddings + top-k retrieval + single answer prompt, no LangChain/FAISS), run the same 25 questions from Day 3, and compare LLM-only vs RAG. Then: try to actually make RAG _good_.

## Setup (final config)

- **Docs:** Day 3's NIST SP 800-53 Rev 5 (492pp) + Moby-Dick (523pp).
- **Chunking:** page → ~180-word sub-chunks (40-word overlap); NIST bibliography pages (401-420) excluded.
- **Embeddings:** `mxbai-embed-large` (334M) via local Ollama. Cosine similarity by hand, top-5.
- **Answer model:** `llama-3.1-8b-instant` via Groq, `temperature=0`. Same model for both LLM-only and RAG, so the comparison is fair.
- Code: [`task.py`](task.py), [`score.py`](score.py). Raw outputs in `run_results.json` / `scoring_results.json`; every experiment below is checkpointed to its own `*_<variant>.json`.

## Results (final)

| Metric             | LLM-only | RAG       |
| ------------------ | -------- | --------- |
| Answer correctness | 14/25    | **16/25** |
| Citation present   | 0/25     | **11/25** |

RAG finally beats LLM-only — but only after real work. The first version (below) _lost_.

## LLM-only vs RAG — where each won

| Bucket             | Questions                  | Why                                                                                                                                                                     |
| ------------------ | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **RAG helped** (6) | Q6, Q9, Q10, Q18, Q23, Q24 | Obscure facts the LLM didn't know (NIST pub date, a control's exact sub-clause) or trap questions where the LLM confidently made something up and RAG correctly refused |
| **RAG hurt** (4)   | Q3, Q11, Q13, Q15          | Famous facts the 8B knew cold (Moby-Dick opening line, ship, narrator's friend), where retrieval didn't surface the exact defining page so RAG refused                  |
| **Both wrong** (5) | Q4, Q5, Q7, Q8, Q17        | Structural "what is the title of control AC-2 / Chapter 28" lookups — semantic search is blind to identifiers, so neither found the right page                          |

## The journey — what actually moved the needle

We started at RAG 10/25 (worse than LLM-only's 14) and treated it as an experiment: change **one** variable, measure, keep or revert. Nothing was accepted on faith.

| #   | Change                                                 | RAG       | Verdict                                                                |
| --- | ------------------------------------------------------ | --------- | ---------------------------------------------------------------------- |
| 0   | Baseline: whole-page chunks, `nomic-embed-text`, top-3 | 10/25     | starting point                                                         |
| 1   | Add `search_query:`/`search_document:` prefixes        | 9/25      | ❌ **reverted** — documented "best practice", measured as a regression |
| 2   | Smaller chunks (180 words)                             | 11/25     | ✅ kept                                                                |
| 3   | Exclude NIST bibliography pages                        | 11/25     | ➖ no score change, but stopped cross-doc contamination                |
| 4   | Top-k = 5                                              | 11/25     | ❌ wrong lever (see below)                                             |
| 5   | **`mxbai-embed-large`** (bigger embedding model)       | **16/25** | ✅✅ the one big win                                                   |
| 6   | Bigger _answer_ model (llama-3.3-70b)                  | wash      | ❌ fixed 1, broke 1, then hit quota                                    |

Three lessons that stuck:

- **"Best practice" ≠ improvement on your data.** The nomic prefix convention (step 1) is real and documented, but on our corpus it shifted the whole embedding space and made NIST's citation-dense pages rank higher for the wrong queries. Only measuring caught it.
- **Match the knob to the failure.** Top-k did nothing (step 4) because the correct pages were ranked _529th, 1317th, 241st_ — not "just outside top-3". No k fixes that; it's an embedding-quality problem. Swapping to a stronger embedding model (step 5) pulled those same pages to rank 15 / 116 / 73 — a 3-35× jump — and that's what actually helped.
- **A bigger model isn't automatically better.** The 70b answer model (step 6) fixed one over-cautious refusal but introduced a different one, netting zero. The generation failures were noise, not a capability gap.

## Topic 1 — RAG flow: query → retrieve → answer

1. **Query** — the question, as-is.
2. **Retrieve** — embed the query to a 1024-dim vector, cosine-compare against every pre-computed chunk vector, take the top-5.
3. **Answer** — put those 5 chunks + the question in one prompt, tell the model to answer only from them and cite the page, call the LLM once.

No agents, no re-ranking. Simple RAG is just steps 2-3 wrapped around a normal call.

## Topic 2 — Retrieval failure vs generation failure

They look identical from outside ("NOT IN DOCUMENT" or a wrong answer), but the fix is opposite, and we hit both:

- **Retrieval failure** — the answer chunk never made it into the top-5, so the model genuinely wasn't given it (Q4: the AC-2 definition page ranked 17th). Fix the _retriever_.
- **Generation failure** — the answer _was_ in the retrieved chunks and the model still refused (Q3: "Program Management" was right there in the top-5 text; the 8B said NOT IN DOCUMENT anyway). Fix the _prompt or model_.

We only knew which was which by re-checking, for each failure, whether the answer text was actually in the retrieved context. Debugging RAG blind — assuming the LLM is wrong when it's really the retriever, or vice versa — means fixing the wrong half.

## Topic 3 — Why "LLM answered confidently but wrong" happens

Our two trap questions are the clean examples (LLM-only, no context):

- **Q23** (Ahab's wife's name): correctly said it's not given — then invented "she died at sea, driving Ahab's obsession." Pure fabrication, delivered as fact, because a tragic-dead-wife backstory _fits the genre_.
- **Q24** (year the story is set): stated "1841" flatly. The novel never gives a year.

The model has no separate "certain" vs "guessing" voice — confident phrasing is just the default way to write a sentence, whether the claim is solid or invented. This is exactly why RAG + "say NOT IN DOCUMENT if unsure" matters: on Q23/Q24, grounded RAG correctly refused where the bare LLM confidently lied.

## Where we'd go next

The 5 stuck questions (Q4/5/7/8/17) are all exact-identifier lookups — a **keyword** job, not a semantic one. The right next step is **hybrid retrieval**: fuse BM25 (nails "AC-2", "Chapter 28" as exact tokens) with dense embeddings (handles conceptual questions). That's the standard production architecture and the one lever left that targets this specific cluster. Left as the next iteration.
