# Week 2 – Day 1 Report — Chunking Strategies & Retrieval Quality

## Task

Index the **same** corpus three ways — **fixed-size**, **overlapping**, and one advanced strategy (**recursive / boundary-aware**) — run the same questions across all three, and measure **hit-rate@5**. Then look at where the advanced strategy helped and where it hurt.

We reuse Day 5's corpus (Kafka, _The Metamorphosis_) so results stay comparable with the LLM-only and simple-RAG baselines from last week.

## Setup

| Component | Choice                             | Note                                                         |
| --------- | ---------------------------------- | ------------------------------------------------------------ |
| Corpus    | _The Metamorphosis_ (21,935 words) | same as Day 5                                                |
| Embedder  | `mxbai-embed-large` (Ollama)       | identical for all 3 indexes                                  |
| Vector DB | Chroma, cosine                     | one collection per strategy                                  |
| Questions | 18 answerable + 2 traps            | Day-5's 10 Qs + 10 new, facts spread 0→100%                  |
| Metric    | **hit-rate@5**                     | is a chunk that _actually contains the answer_ in the top-5? |

**The three strategies** — each changes exactly **one** thing vs. the fixed baseline, so any difference is attributable to that one thing:

| Strategy        | Cuts fall…                                  | Overlap        | Chunks | Avg words |
| --------------- | ------------------------------------------- | -------------- | ------ | --------- |
| **fixed**       | every 150 words (arbitrary)                 | none           | 147    | 149       |
| **overlapping** | every 150 words (arbitrary)                 | 30 words (20%) | 183    | 150       |
| **recursive**   | on natural boundaries (¶ → sentence → word) | none           | 147    | 149       |

> Rigor note: I first ran recursive at ~127 words/chunk and it looked much worse — but that was a **size** confound, not boundaries. Re-tuning recursive to average **149 words (same as fixed)** isolated the real variable. Half of recursive's apparent penalty vanished. Lesson logged.

**Hit-detection is strict:** each question has a `gold_phrase` that occurs _only_ where the real answer is (e.g. `"his last breath flowed weakly from his nostrils"`). A chunk counts as relevant only if it contains that phrase — not just a loose keyword. Traps are excluded (no relevant chunk exists). Code: [`task.py`](task.py), [`score.py`](score.py), questions in [`test_set.json`](test_set.json).

## Results

| hit-rate | fixed           | overlapping | recursive   |
| -------- | --------------- | ----------- | ----------- |
| **@5**   | **15/18 (83%)** | 13/18 (72%) | 14/18 (78%) |
| @3       | 14/18 (78%)     | 12/18 (67%) | 13/18 (72%) |
| @1       | 9/18 (50%)      | 8/18 (44%)  | 6/18 (33%)  |

**Plain fixed chunking won.** Recursive nearly tied it (one question behind); overlapping was clearly weakest. This is the opposite of the textbook "advanced chunking is better" expectation — and the _why_ is the interesting part.

Rank of the first answer-bearing chunk (`miss` = not in top-10):

| Q                   | fact @ | fixed    | overlap | recursive |                      |
| ------------------- | ------ | -------- | ------- | --------- | -------------------- |
| Q1 vermin           | 0%     | 1        | 1       | 1         |                      |
| Q2 salesman         | 0%     | 1        | 1       | 1         |                      |
| Q3 sister "Grete"   | 19%    | **1**    | miss    | 3         | overlap crowded out  |
| Q4 violin           | 44%    | 1        | 1       | 1         |                      |
| Q5 apple            | 65%    | 1        | 1       | 3         |                      |
| Q6 three lodgers    | 68%    | 2        | 1       | **1**     | recursive ↑          |
| Q7 he dies          | 91%    | **miss** | miss    | **1**     | recursive win        |
| Q8 tram trip        | 98%    | miss     | miss    | miss      | everyone missed      |
| Q11 "dung-beetle"   | 75%    | 1        | 2       | 2         |                      |
| Q12 chief clerk     | 12%    | 1        | 1       | 2         |                      |
| Q13 fur picture     | 1%     | **2**    | miss    | **miss**  | recursive buried it  |
| Q14 cheese          | 38%    | 2        | 2       | **1**     | recursive ↑          |
| Q15 gold buttons    | 63%    | 3        | 1       | 2         |                      |
| Q16 key/mouth       | 21%    | 4        | 3       | 5         |                      |
| Q17 "get rid of it" | 86%    | miss     | miss    | miss      | everyone missed      |
| Q18 body discovered | 92%    | **3**    | 5       | **miss**  | recursive dropped it |
| Q19 Grete grown     | 100%   | 1        | 1       | 3         |                      |
| Q20 hissing         | 30%    | 1        | 2       | 2         |                      |

## The concepts, grounded in this run

**1. Fixed vs. overlapping.** Fixed cuts disjoint 150-word windows. Overlapping repeats the last 30 words of each chunk in the next, so a fact straddling a boundary stays whole somewhere. The cost: +24% more chunks, and neighbours become **near-duplicates**. On Q11 the overlapping index retrieved chunks 136-137-138 — the _same passage three times_ — burning 3 of 10 slots and pushing other content out. That crowding is why overlapping scored worst here.

**2. Why poor chunking breaks good embeddings.** A chunk becomes **one** vector — an average of everything in it. Mix two topics and the vector blurs into a mush that matches neither query well.

- **Q7 (recursive wins):** its chunk begins on a clean boundary and holds the whole dying scene ("could no longer move… body aching… last breath") → the vector clearly means _the end_ → rank 1. Fixed's arbitrary window blended that same last-breath line with "thought back of his family… clock tower," muddying the vector — so it lost to unrelated chase-scene chunks and fell out of the top-10.
- **Q13 (recursive loses):** the fur-picture is a one-line _aside_. Recursive tidily packed it into chunk-0 — which is dominated by the famous opening ("horrible vermin… armour-like back"). That chunk screams _transformation_, not _framed picture_, so the detail drowns. Fixed's blind window happened to isolate it into a less-dominated chunk → surfaced at rank 2.

Same mechanism, opposite results. Coherent chunks sharpen a vector when the chunk is _about_ the answer, and bury the answer when it's a minor aside inside a stronger topic.

**3. Recall vs. precision.** Look at @1 vs @5: recursive nails the very top result _less_ often (33% vs fixed's 50%) but catches up by @5 (78% vs 83%). Coherent chunks are "purer" (higher precision per chunk) yet a small fact can fall through the cracks (lower recall on asides). More overlap / more chunks buys recall but spends precision on duplicates. There's no free lunch — you tune chunking to which end you care about.

**4. The advanced family.** _Recursive_ = split on a priority list of separators (paragraph → line → sentence → word), dropping to a finer one only when a piece is too big — what we built. _Sentence-based_ is the special case where the boundary is always the sentence. _Hierarchical / section-based_ uses document structure (headings/sections) and can retrieve at multiple granularities. Note: hierarchical needs **structure to exploit** — a novel has almost none, which is part of why no clever strategy pulled ahead here.

## Where recursive improved retrieval, and where it hurt

**Improved (5):**

| Q                 | vs.             | change       | why                                               |
| ----------------- | --------------- | ------------ | ------------------------------------------------- |
| Q7 he dies        | fixed & overlap | miss → **1** | whole death scene kept in one coherent chunk      |
| Q6 three lodgers  | fixed           | 2 → 1        | boundary-aligned chunk = cleaner "lodgers" vector |
| Q14 cheese        | fixed           | 2 → 1        | the food passage isn't split across a window edge |
| Q15 gold buttons  | fixed           | 3 → 2        | father's-uniform description stays intact         |
| Q3 sister "Grete" | overlapping     | miss → 3     | no duplicate neighbours crowding the top-k        |

**Worse (3):**

| Q                    | vs.   | change       | why                                                                            |
| -------------------- | ----- | ------------ | ------------------------------------------------------------------------------ |
| Q13 fur picture      | fixed | 2 → **miss** | aside buried inside the transformation-dominated opening chunk                 |
| Q18 body discovered  | fixed | 3 → **miss** | discovery line packed with surrounding "cleaner" chatter, vector diluted       |
| Q5 apple / Q19 Grete | fixed | 1 → 3        | near-tied distances; coherent chunk demoted the exact answer chunk a few spots |

The full rank table above is the honest, un-cherry-picked record; these are the clearest cases from it.

## Conclusion

On this corpus, **advanced chunking did not beat naive fixed chunking** — it roughly tied it, and overlapping was worse. That's a real result, not a bug, and it lines up with Day 4's lesson: _a documented best practice is a hypothesis, not a guarantee on your data._ Three reasons it played out this way here:

1. **The corpus is flowing narrative prose.** Boundary-aware and hierarchical chunking earn their keep on _structured, heterogeneous_ documents (headings, tables, code, lists) where an arbitrary cut genuinely destroys meaning. A novel restates facts and flows smoothly, so arbitrary cuts rarely hurt.
2. **The metric is factoid hit-rate.** hit-rate@5 rewards whichever chunk holds the keyword. It doesn't measure the thing advanced chunking most improves — **answer quality at generation time**, where a clean, coherent chunk reads better than a sentence sliced in half.
3. **Distances are tightly clustered** (many chunks sit at cosine ~0.27–0.31). With only 18 questions, which near-tied chunk lands at rank 5 vs. 6 is partly luck, and chunking just perturbs that lottery.

**What would actually move the needle** (next-day candidates): combine recursive **with** overlap (the Q7 win + boundary protection, without the smaller-chunk penalty), or test these strategies on a _structured_ document where boundaries carry real meaning — that's the home turf where advanced chunking is supposed to shine.

---

## Follow-up: can other strategies get us to 100%? (and why not)

Two follow-up questions: _try more strategies_, and _what would give 100% — and why don't these?_ Code: [`explore.py`](explore.py). Short answer: **nothing here reaches 100%, and it turns out that's not a chunking problem at all.**

### 1. More chunking strategies — none beats plain fixed

| Strategy                     | hit@5           |
| ---------------------------- | --------------- |
| **fixed (150w)**             | **15/18 (83%)** |
| recursive                    | 14/18 (78%)     |
| overlapping                  | 13/18 (72%)     |
| recursive + overlap          | 12/18 (67%)     |
| large (300w)                 | 12/18 (67%)     |
| semantic (topic-shift split) | 12/18 (67%)     |
| small (75w)                  | 8/18 (44%)      |

Takeaways: **small chunks collapse** (44%) — 293 tiny chunks means the answer chunk competes with far more look-alikes and rarely makes the top-5 (low recall). **Large chunks also drop** (67%) — each vector now averages more topics, so ranking gets muddier (the "blurred vector" effect again). **recursive+overlap** (my predicted winner) actually _lost_ to plain recursive — overlap's duplicate-crowding cancelled the coherence gain. Even fancy **semantic chunking** didn't help. On flowing prose, cleverer cutting isn't the lever.

### 2. The ceiling of chunking: ~89%, and two questions are unreachable

If we let an _oracle_ pick the best strategy per question (answer in **any** strategy's top-5):

|                   | hit@5       |
| ----------------- | ----------- |
| fixed ∪ recursive | 16/18 (89%) |
| union of all 7    | 16/18 (89%) |

Adding five more strategies past `fixed ∪ recursive` buys **nothing**. **Q8** (tram trip) and **Q17** ("get rid of it") miss in _every_ chunking strategy — their answer chunk ranks 78th and 16th out of 147 no matter how you cut. That's the signature of a **semantic mismatch**, not a boundary problem.

### 3. Why those two are stuck — the query↔answer gap

The question and its answer share **neither** vocabulary nor close meaning:

|     | question contains…                              | answer contains…                                |
| --- | ----------------------------------------------- | ----------------------------------------------- |
| Q8  | "what do the family **do** after his **death**" | "took the **tram** out to the open **country**" |
| Q17 | "what must the family **do** about Gregor"      | "we have to **get rid of it**"                  |

So the levers that "should" fix retrieval both **backfired** — and the failures are the lesson:

| Lever                                             | Result        | Why it failed                                                                                                                                                                             |
| ------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Raise k (5→20)                                    | 83% → 89%     | Q17 surfaces at k=20; Q8 sits at rank 78 — you'd retrieve half the book                                                                                                                   |
| **Hybrid** BM25+dense                             | 83% → **39%** | BM25 needs the _question_ to carry the answer's rare words. It doesn't ("tram" is nowhere in the question), so BM25 ranked common-word ("gregor", "family") chunks and dragged dense down |
| **HyDE** (LLM drafts an answer, retrieve with it) | 83% → **67%** | the 3B model _hallucinated_ the draft — for Q8 it wrote "the family sell Gregor's belongings," pulling retrieval toward the wrong content                                                 |

---
