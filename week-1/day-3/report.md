# Week 1 – Day 3 Report

## Task

1. Pick 2 real 100+ page PDFs, build a 25-question test set (20 answerable + 5 not-in-document), with ground truth.
2. Run all 25 on LLM-A vs LLM-B at `temperature=0`.
3. Score both on 4 metrics + pass/fail.

## Setup

- **PDF 1:** [NIST SP 800-53 Rev 5](pdfs/nist_sp800-53r5.pdf) — the real, official 492-page US government security controls catalog, downloaded directly from nist.gov. Dense, technical, highly structured.
- **PDF 2:** [Moby-Dick](pdfs/moby_dick.pdf) — 523 pages. Gutenberg doesn't host a native PDF for this one, so I fetched the real, unaltered public-domain text directly from Project Gutenberg and generated the PDF myself. Narrative, unstructured — a deliberate contrast to PDF 1.
- **Models:** `llama-3.3-70b-versatile` (LLM-A, 70B) vs `llama-3.1-8b-instant` (LLM-B, 8B) via Groq, `temperature=0`, identical prompt template for both.
- **Test set:** [`test_set.json`](test_set.json) — 20 questions with verified ground truth (I read the actual extracted text, not memory) + 5 deliberately unanswerable ones (an org-defined NIST parameter with no fixed value, a CVE that's never cited, an unnamed character detail, an unstated date, and a nonsense question mixing both documents).
- Full pipeline: [`task.py`](task.py) (retrieval + model calls) → [`run_results.json`](run_results.json) (raw outputs) → [`score.py`](score.py) (metrics) → [`scoring_results.json`](scoring_results.json).

## Results

| Metric | llama-3.3-70b (LLM-A) | llama-3.1-8b (LLM-B) |
| --- | --- | --- |
| Exact fact match rate | **0.80** | 0.75 |
| Token-level F1 | **0.672** | 0.660 |
| Abstention accuracy (5 unanswerable Qs) | 1.00 | 1.00 |
| Groundedness (answer content traceable to retrieved text) | 0.981 | **0.996** |

## Pass/Fail Summary

| Model | Passed | Failed | Pass rate |
| --- | --- | --- | --- |
| llama-3.3-70b-versatile | 21/25 | 4 | **84%** |
| llama-3.1-8b-instant | 20/25 | 5 | 80% |

The bigger model wins narrowly on raw accuracy, as expected — but not by much, and both models were **perfect on the hallucination trap** (5/5 unanswerable questions correctly declined by both, no fabrication either direction). The real story is in *which* questions each model missed, not how many.

## Top 5 Failures

| # | Question | Model | What happened | Why |
| --- | --- | --- | --- | --- |
| 1 | Title of control AU-2 | **llama-3.3-70b** | Said "NOT IN DOCUMENT" | The correct text ("AU-2 EVENT LOGGING") was sitting right in its retrieved context — the *smaller* model got this one right |
| 2 | Title of control CP-9 | Both models | Both said "NOT IN DOCUMENT" | The heading was genuinely present, but tucked in right after unrelated CP-8 content near the end of a page — both models missed it |
| 3 | AC-2's account review requirement | llama-3.1-8b | Said "NOT IN DOCUMENT" | Same context given to both; llama-3.3-70b found it correctly, the 8B model didn't |
| 4 | Moby-Dick's opening line | Both models | Both correctly said "NOT IN DOCUMENT" | Not a model failure — my retriever never found the actual page (page 20). Both models correctly refused rather than answering from pretrained memory, which is the *right* call even though it counts as a missed answer |
| 5 | Moby-Dick's full title | llama-3.1-8b | Said "NOT IN DOCUMENT" | The title page text was in context; llama-3.3-70b read it correctly, the 8B model didn't |

## What I'd take away from this

- **The bigger model isn't dramatically better — it's just slightly more reliable at reading carefully.** Every single failure (except the retrieval miss) was a case of the answer being right there in the text and one model simply not finding it. This wasn't a knowledge gap, it was a reading-comprehension gap.
- **Groundedness being high for both is the most reassuring number here.** Neither model padded its answers with outside knowledge — when they answered, they stuck to what was actually given to them. Combined with the perfect abstention score, neither model hallucinated on the 5 trap questions.
- **The retrieval layer, not the models, caused one of the 5 "hardest" failures.** Q11/Q12 failed because my keyword-based retriever never found the right page (the question said "famous opening line," which shares no literal words with "Call me Ishmael"). Worth remembering when debugging a real RAG system: a wrong answer doesn't always mean the LLM is broken — check what it was actually given first, which is exactly why I made `run_results.json` log the full retrieved context per question.
- **What I'd improve next:** swap the keyword/BM25 retriever for an embedding-based one (would catch the Q11-style misses), and re-run CP-9 specifically with a larger `k` to see if giving the model more surrounding pages fixes the shared miss.
