# Week 2 – Day 2 Report (Course Day 7) — Query Optimization & Metadata-Aware Retrieval

## Task

Take one vector index, retrieve the **same 20 questions** two ways — **baseline** (embed the raw question) vs **optimized** (query optimization + metadata filters) — and measure hit-rate@5. Then dissect *where* optimization helped and where it didn't.

Two topics, three query techniques implemented ([queries.py](queries.py)):

| Query optimization | Fixes | Metadata |
| --- | --- | --- |
| **HyDE** (hypothetical doc embedding) | question ≠ answer phrasing | attached at **ingestion** ([ingest.py](ingest.py)) |
| **Multi-query** rewriting | one phrasing = one narrow probe | used as **filters** at query time ([retrieve.py](retrieve.py)) |
| **Sub-query** decomposition | compound question = blurred vector | via an LLM **router** → doc_type filter |

## Setup

| Component | Choice | Note |
| --- | --- | --- |
| Corpus | **3 heterogeneous docs** | so metadata filters actually mean something |
| — Metamorphosis (Kafka, 1915) | fiction | 153 chunks, 3 parts |
| — Moby-Dick (Melville, 1851) | fiction | 310 chunks, 28 chapters, real page #s |
| — NIST SP 800-53r5 (2020) | standard | 429 chunks, 71 controls, real page #s |
| Embedder / DB | `mxbai-embed-large` + Chroma (cosine) | identical for every strategy |
| Query LLM | Groq `llama-3.3-70b` | HyDE / multi-query / decomposition / routing |
| Metric | **hit-rate@5** (strict gold phrase) | compound = **all** sub-facts must appear in top-5 |

Metadata attached per chunk, parsed from real markers in the text (`<<<PAGE 94>>>`, `CHAPTER 3.`, `AC-2 ACCOUNT MANAGEMENT`): `source, title, author, doc_type, date, section, page, position_pct`. Markers are stripped from the chunk body so they don't pollute the embedding.

## Results — hit-rate@5

| retriever | hit@5 | vs baseline |
| --- | --- | --- |
| **baseline** (raw query) | **15/18 (83%)** | — |
| hyde | 15/18 (83%) | tie (but rescues Q7 — see below) |
| filtered (router) | 15/18 (83%) | tie (inert — see metadata section) |
| multiquery | 14/18 (78%) | **worse** |
| **optimized** (the works) | **15/18 (83%)** | **tie** |

**The headline is a tie** — the same result you found on Day 1: *a documented best practice is a hypothesis, not a guarantee on your data.* But the tie hides real, opposite movements underneath.

Rank of first correct chunk (`miss` = not in top-5; compound = facts covered):

| Q | category | baseline | multiquery | hyde | filtered | optimized |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 vermin | factoid | **1** | 1 | 2 | 1 | 2 |
| Q3 violin | factoid | **1** | 1 | 1 | 1 | 2 |
| Q5 Spouter-Inn | factoid | 5 | 4 | **3** | 5 | 3 |
| Q6 Queequeg | factoid | 4 | 4 | **1** | 4 | 3 |
| Q7 Jonah/Mapple | factoid | **miss** | miss | **1** | miss | **miss** |
| Q8–Q14 NIST | factoid | 1–2 | 1–2 | 1 | 1–2 | 1–3 |
| Q15 least-priv (cross) | cross | 2 | **1** | **1** | 2 | **1** |
| Q16 Kafka compound | compound | **2/2** | 1/2 | 1/2 | 2/2 | 2/2 |
| Q17 narrator+NIST | compound | 0/2 | 0/2 | **1/2** | 0/2 | **1/2** |
| Q18 AC-2+SoD | compound | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |

## Where query optimization improved results

**HyDE was the one lever that actually worked here.** Because a question and its answer are written differently, HyDE searches with a *fake answer* — phrased like the target document — and lands nearer the real chunk:

| Q | baseline | HyDE | why |
| --- | --- | --- | --- |
| **Q7 Jonah** | **miss** | **rank 1** | the question ("biblical figure in Father Mapple's sermon") shares no words with the chapel chunk; HyDE's passage mentions *Jonah, whale, sermon* → matches |
| Q6 Queequeg | 4 | **1** | HyDE describes a harpooneer sharing a bed → sharpens the vector onto that scene |
| Q5 Spouter-Inn | 5 | 3 | HyDE names the inn/New Bedford directly |
| Q15 least privilege | 2 | **1** | HyDE writes the control definition, matching NIST's own wording |

This flips your Day-1 result where HyDE *hurt* (83→67) — there a tiny 3B model hallucinated wrong facts. A 70B model hallucinates *plausibly enough* to help. **The technique didn't change; the model quality did.** That's the lesson: HyDE's value is bounded by how factually the LLM can fake the answer.

## 5 failure cases where optimization did **not** help

| # | Q | what happened | root cause |
| --- | --- | --- | --- |
| 1 | **Q4 "Call me Ishmael"** | miss in **every** retriever, HyDE included | **query↔answer semantic gap.** The famous opening chunk ("…little or no money in my purse… sail about") shares zero vocabulary with "who is the narrator / how does the novel begin." It's a semantic island; no query rewrite reaches it. (Same signature as your Day-1 Q8/Q17.) |
| 2 | **Q7 Jonah** | HyDE alone = rank 1, but **"optimized" = miss** | **fusion dilution.** Optimized fuses 3 multi-query probes (all miss Jonah) + 1 HyDE probe (rank 1) with RRF. Three mediocre votes outweigh one excellent vote → Jonah pushed out of top-5. Combining techniques *cancelled* a win. |
| 3 | **Q16 Kafka compound** | baseline **2/2** → multiquery **1/2** | **expansion adds noise.** Paraphrases of "what instrument does his sister play" pulled generic music/family chunks that crowded out the violin chunk. More probes = more recall *and* more distractors. |
| 4 | **Q17 narrator + NIST** | best case only **1/2** | half is unreachable (the Ishmael gap, #1) **and** the strict compound bar needs *both* facts. Decomposition + per-sub filter correctly got the *least-privilege* half; the Ishmael half stayed an island. |
| 5 | **Q1 / Q3 easy factoids** | baseline **rank 1** → optimized **rank 2** | **optimization is a tax on easy queries.** Questions baseline already nails get *demoted* a slot by HyDE's added text / fusion reshuffling. Optimizing a query that didn't need it can only lose. |

## Metadata-aware retrieval — the honest finding

The metadata filter was **inert on hit-rate (83% → 83%)**, and measuring *why* is the real lesson:

| Measurement | Result | Meaning |
| --- | --- | --- |
| Wrong-source chunks in baseline top-5 (17 single-source Qs) | **0** | vector search *already* perfectly separated a novel from a security standard — nothing for a filter to remove |
| Force **wrong** filter on Q8 (least privilege → `doc_type:fiction`) | rank 1 → **miss** | the filter **cliff**: a wrong route excludes the answer outright; no ranking recovers it |

Two first-principles fall out:

1. **Filters only pay off when sources overlap in embedding space.** Here Kafka, Melville and NIST are so far apart semantically that the embedder never confused them, so the filter is redundant. Where filters *do* earn their keep: 10,000 near-identical support tickets separable only by `date`/`product`/`customer`, or multiple versions of the same doc — cases meaning alone can't disambiguate.
2. **A filter is a cliff, not a nudge.** Query optimization only *re-ranks* the same candidates (worst case: no change). A filter *removes* candidates before ranking — upside is less noise, downside is a hard miss if the router is wrong. That asymmetry is why filters need a **high-precision** router, and why the cross-source compound Q17 had to route to "both" (no filter): a single filter would have killed one half.

## Conclusion

- **HyDE is the technique that moved the needle** on this corpus (rescued Q7, improved Q5/Q6/Q15) — and its power scaled with LLM quality (70B helped where Day-1's 3B hurt).
- **Multi-query and naive fusion can backfire**: wider nets add distractors (Q16), and RRF lets many weak probes outvote one strong one (Q7). Combining techniques is *not* additive.
- **Metadata filters were inert here** because the sources don't collide — a genuine result about *when* filters matter, plus a clean demo of their cliff risk.
- **The remaining misses aren't chunking or query problems** — Q4/Q17 are query↔answer semantic gaps, the same wall you hit on Day 1. The fix for those lives elsewhere: better embeddings, or generation-time reasoning over a wider `k`.

**Next-day candidates:** (a) weight fusion toward high-confidence probes so HyDE's Q7 win survives; (b) test filters on a corpus that *does* collide (versioned/dated near-duplicates) so metadata earns its keep; (c) a reranker to attack the semantic-gap misses.
