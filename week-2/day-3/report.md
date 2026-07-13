# Week 2 – Day 3 Report (Course Day 8) — Retrieval Strategies & Reranking

## Task

On the Day-7 mixed corpus (892 chunks: Kafka + Melville + NIST), compare **how we retrieve** (vector vs BM25 vs hybrid) and then **whether reranking the results improves the final answer**. Two independent measurements:

1. **hit-rate@5** — vector vs BM25 vs hybrid (retrieval only).
2. **answer correctness + citation accuracy** — no-rerank vs cross-encoder vs LLM reranking, generating answers with `gpt-oss-120b`.

Code: [bm25.py](week-2/day-3/bm25.py) (from-scratch BM25), [retrieve.py](week-2/day-3/retrieve.py), [rerank.py](week-2/day-3/rerank.py) (real ms-marco cross-encoder + LLM reranker), [generate.py](week-2/day-3/generate.py), [task.py](week-2/day-3/task.py), [score.py](week-2/day-3/score.py). 23 questions (21 answerable + 2 traps), category `lexical` added to stress exact-term matching.

## The two-stage mental model

```
 STAGE 1 — RETRIEVE (cheap, wide net, optimizes RECALL)   STAGE 2 — RERANK (expensive, precise, optimizes PRECISION)
   query ─┬─ vector (bi-encoder: meaning) ─┐                             ┌─ top-5 clean context ─► LLM answer
          └─ BM25   (lexical: words)     ──┴─ RRF = hybrid top-15 ──────►┤
                                                                          └─ cross-encoder / LLM re-sorts
```

- **Bi-encoder (vector):** query and chunk are embedded *separately*, then compared. Fast (chunks pre-embedded), but the two never interact inside the model, so it's good at "topically near", weak at "this exact chunk answers this exact question."
- **Cross-encoder / LLM (rerank):** feed `[query, chunk]` *together* so every query token attends to every chunk token → a far sharper relevance score. Too slow for the whole corpus, perfect for re-scoring ~15 candidates. **That split is the reason reranking exists.**

## Results

### Table 1 — hit-rate@5 (21 answerable)

| retriever | hit@5 | note |
| --- | --- | --- |
| **vector** | **16/21 (76%)** | strong embedder already handles most questions |
| bm25 | 12/21 (57%) | weak alone — fiction questions rarely share words with answers |
| hybrid (equal-weight RRF) | 14/21 (67%) | **worse than vector** — see why below |
| **hybrid (vector-weighted, w_lex=0.4)** | **16/21 (76%)** | recovers vector's level *and* keeps BM25's rescues |

### Table 2 — answer correctness (21 answerable)

| reranking | correct | vs none |
| --- | --- | --- |
| none (hybrid top-5) | 13/21 (62%) | — |
| cross-encoder | 13/21 (62%) | **no change** |
| **LLM (gpt-oss-120b)** | **15/21 (71%)** | **+2 (Q6, Q7)** |

### Table 3 — citation accuracy (21 answerable)

| reranking | accurate | vs none |
| --- | --- | --- |
| none | 14/21 (67%) | — |
| cross-encoder | 14/21 (67%) | no change |
| **LLM** | **16/21 (76%)** | **+2 (Q6, Q7)** |

> Measurement note: `gpt-oss-120b` cites with unicode brackets (`【1】`, `[1†L1-L4]`), not just `[1]`. My first citation parser missed those and under-counted accuracy by ~20 pts. Fixed in [score.py](week-2/day-3/score.py) (`_CITE_RE`) and re-scored from stored answer text. Lesson logged: *validate your metric's parser before trusting the metric.*

## Analysis 1 — where hybrid retrieval improved (and why only there)

Hybrid beat vector on **exactly 2 of 21** questions — the cases it is *supposed* to win, where the query carries a rare exact token the embedder blurs:

| Q | vector | bm25 | hybrid | why hybrid won |
| --- | --- | --- | --- | --- |
| **Q9** account mgmt | 2 | 3 | **1** | BM25's exact hit on "account" + vector agreeing → RRF floats it to rank 1 |
| **Q17** narrator + least privilege | **miss** | **1** | 2 | vector missed the NIST half entirely; BM25's exact match on "least privilege" **rescued** it into the results |

**But naive hybrid *hurt* 3 questions** (Q5, Q6, Q15) and netted below vector (67% vs 76%). Mechanism: equal-weight RRF lets BM25's *confident-but-wrong* chunks (it always finds *some* word overlap) outvote vector's correct-but-fuzzy hits. On a corpus that's mostly fiction (where questions and answers share little vocabulary), BM25 is the weaker retriever, so giving it an equal vote drags the fusion down.

**The fix — weight the fusion toward the stronger retriever.** Vector-weighted hybrid (`w_lex=0.4`) recovered to 76%, fixing the Q5/Q16 losses *while keeping* BM25's Q17 rescue. **Takeaway: hybrid is not "vector + BM25"; it's "vector + BM25 × the right weight," and the weight is the whole game.** Equal-weight is a bad default when one retriever is clearly stronger.

## Analysis 2 — where reranking helped (the day's clearest win)

**Why top-k alone is insufficient, made concrete.** For Q7 ("biblical figure in Father Mapple's sermon"), hybrid *did* retrieve the Jonah chunk — at pool ranks **9 and 14**, below the top-5 the LLM sees. So the no-rerank answer was "NOT IN CONTEXT" despite the answer being *right there in the retrieved set*. Reranking's entire job is to fix that ordering:

| Q | gold chunk in pool | no-rerank top-5 | cross-encoder top-5 | LLM rerank top-5 | result |
| --- | --- | --- | --- | --- | --- |
| **Q7** Jonah | ranks 9, 14 | absent → *NOT IN CONTEXT* | **absent** | **ranks 1, 2** | LLM: correct + cited |
| **Q6** Queequeg | ranks 7–15 | absent → *NOT IN CONTEXT* | **absent** | **ranks 1, 2, 3** | LLM: correct + cited |

The surprise: **the general LLM reranker beat the specialized cross-encoder.** The ms-marco cross-encoder is trained on web-search relevance and didn't recognize that "Father Mapple's sermon" ↔ *Jonah* or "harpooneer Ishmael shares a bed with" ↔ *Queequeg* — indirect, literary relevance. The LLM reasons about it and surfaced the chunk. On this corpus the cross-encoder changed **zero** outcomes; the LLM changed two.

That is not a knock on cross-encoders in general (they dominate on the technical/QA text they're trained for, and they're ~100× cheaper than an LLM call). It's the same lesson as every day this week: **the "best-practice" tool is a hypothesis — it wins on its home turf, not universally.**

## Conclusions

1. **Vector search is a strong baseline; hybrid only helps when weighted.** Naive equal-weight hybrid *lost* to vector here (67% vs 76%) because BM25 is the weaker retriever on fiction-heavy, low-lexical-overlap questions. Vector-weighted hybrid tied vector *and* kept BM25's one genuine rescue (Q17). Hybrid's real value is **robustness to vector's blind spots** (rare tokens, exact IDs), not a higher average.
2. **Reranking is the day's clear win — and it's about ORDER, not retrieval.** The answer was often *already retrieved* but ranked below top-5 (Q6, Q7). Reranking is how you recover it. LLM reranking lifted correctness 62%→71% and citations 67%→76%.
3. **Reranker choice is corpus-dependent.** The LLM reranker beat the ms-marco cross-encoder on indirect fiction relevance; expect the reverse on technical QA. Match the reranker to the domain.
4. **Trust your metric only after you've checked its parser** — the unicode-citation bug would have understated the LLM reranker by 20 points.

**Next-day candidates:** (a) tune the hybrid weight per query type (lexical→more BM25, semantic→more vector); (b) try a cross-encoder trained on QA/NLI instead of ms-marco web search; (c) attack the remaining hard misses (Q4/Q21 — the Day-7 semantic-gap wall) with a stronger embedder or query rewriting feeding into this rerank stage.
