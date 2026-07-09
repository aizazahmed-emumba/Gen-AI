# Week 1 – Day 5 Report — Chroma DB & Open-Source LLMs

## Task

Build a **basic** RAG pipeline with Chroma DB as the vector database, and compare it against passing the **full document** to the LLM with no retrieval. Everything open-source and local.

## Setup — fully local stack (no cloud, no rate limits)

| Component  | Choice                                                    | Role                                                           |
| ---------- | --------------------------------------------------------- | -------------------------------------------------------------- |
| Document   | Kafka, _The Metamorphosis_ (21,935 words / 27,633 tokens) | one moderate doc so "full text" is actually attemptable        |
| Chunking   | fixed **150 words**, no overlap                           | the simple, no-frills strategy the task asked for → 147 chunks |
| Embeddings | `mxbai-embed-large` (Ollama)                              | text → vectors                                                 |
| Vector DB  | **Chroma** (persistent, on disk)                          | store vectors + fast similarity search                         |
| Answer LLM | `llama3.2:3b` (Ollama)                                    | open-source, runs on the laptop                                |

Two strategies, same model, same questions:

- **RAG** — Chroma returns the top-4 chunks for the question → answer from those.
- **Full-text** — stuff the document in directly, but a small model only has room for ~6,000 tokens, so only the **first ~22%** of the book fits; the rest is **truncated** away.

Code: [`task.py`](task.py), [`score.py`](score.py). 10 questions with verified ground truth, deliberately spread from 0%→98% through the document, in [`test_set.json`](test_set.json).

## Results

|               | RAG (Chroma)                                    | Full-text (truncated) |
| ------------- | ----------------------------------------------- | --------------------- |
| **Correct**   | **6/10**                                        | 5/10                  |
| Failure types | 2 retrieval-miss, 1 generation, 1 hallucination | 5 truncation          |

| Q                               | fact is at | RAG              | Full-text    |
| ------------------------------- | ---------- | ---------------- | ------------ |
| Q1 transformed into?            | 0%         | ✅               | ✅           |
| Q2 occupation?                  | 0%         | ✅               | ✅           |
| Q3 sister's name?               | 19%        | ❌ generation    | ✅           |
| Q4 sister's instrument?         | 44%        | ✅               | ❌ truncated |
| Q5 father throws?               | 65%        | ✅               | ❌ truncated |
| Q6 how many lodgers?            | 68%        | ❌ retrieval     | ❌ truncated |
| Q7 Gregor's fate?               | 91%        | ❌ retrieval     | ❌ truncated |
| Q8 family after death?          | 98%        | ❌ hallucination | ❌ truncated |
| Q9 what city? (trap)            | —          | ✅ refused       | ✅ refused   |
| Q10 father's first name? (trap) | —          | ✅ refused       | ✅ refused   |

The pattern is the whole point: **full-text answers everything early and nothing late; RAG answers by relevance regardless of position.**

## Failure cases (the three the task asked about)

- **Truncation** (full-text, Q4-Q8) — the clean, dominant failure. Every fact past the 22% budget was simply never seen by the model, which then correctly said "NOT IN DOCUMENT." Note Q3 at 19% _just_ survived the cutoff and full-text got it — a nice boundary marker. This is exactly why you can't just "paste the whole doc in" once docs get big.
- **Missed info / retrieval miss** (RAG, Q6 & Q7) — the right chunk wasn't in the top-4. Q7 is the instructive one: the death scene is in **chunk-134**, but retrieval returned **chunk-133** — the adjacent chunk. Our fixed 150-word, **no-overlap** chunking split the scene and the key sentence fell just outside the retrieved window. This is precisely the failure that chunk _overlap_ (the "advanced strategy" we deliberately skipped) is designed to prevent.
- **Hallucination** (RAG, Q8) — retrieval missed the ending (chunk-144), and rather than refuse, the 3B model stitched a confident, wrong answer ("they go to Gregor's room, find his corpse, Grete shouts…") out of the unrelated chunks it _did_ get. Wrong chunks in → wrong answer out, stated confidently.
- (Bonus — **generation failure**, RAG Q3: "Grete" was actually inside the retrieved chunks, but the small model refused anyway. Same over-cautious small-model behavior we saw in Day 4 — retrieval did its job, the answerer didn't.)

Both strategies aced the two traps (Q9, Q10) — neither invented a city or a first name the book never gives. Grounding + "say NOT IN DOCUMENT" held.

## Conclusion — where basic RAG helped

RAG only won by **one** point (6 vs 5), and that's an honest, useful result:

- **Where RAG clearly helped:** Q4 and Q5 — facts sitting at 44% and 65% of the document, which the full-text baseline simply couldn't reach because they were truncated away. RAG retrieves by _meaning, not position_, so a fact on page 40 is as reachable as one on page 1. That is the single reason RAG exists: it decouples "what's relevant" from "what fits in the context window."
- **Where basic RAG fell short:** it traded truncation failures for _retrieval_ failures. Our deliberately-basic setup (no chunk overlap, small 3B answer model) caused a near-miss (Q7), a wrong-section retrieval (Q6), and a hallucination (Q8). Day 4 already showed the fixes — overlap, a stronger embedder, a stronger answer model — none of which we applied here on purpose, to keep it "basic."

Net: **the value of RAG showed up exactly where the task predicted — on information the full-document approach truncated — while its weaknesses were all the basic-implementation shortcuts we knowingly took.**

---
