"""
Follow-up: "can we try other strategies, and what would give 100%?"

Part A - more CHUNKING strategies (does any single one hit 100%@5?):
    recursive+overlap, large (300w), small (75w), semantic (topic-shift split)
Part B - the CEILING of chunking: best-case UNION of strategies.
Part C - what chunking CAN'T fix: hit-rate@k curve + a HYBRID (BM25 + dense)
    retriever, which is what actually rescues the semantic-mismatch questions.

Reuses the canonical fixed/recursive/overlapping indexes from task.py; builds the
new chunk strategies in a separate store so the Day-1 deliverable is untouched.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

import chromadb
import ollama

import importlib.util
_spec = importlib.util.spec_from_file_location("task", str(Path(__file__).parent / "task.py"))
task = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(task)

DAY_DIR = Path(__file__).parent
EF = task.OllamaEmbeddingFunction()
norm = lambda s: re.sub(r"\s+", " ", s.lower())


# ── extra chunking strategies ────────────────────────────────────────────────

def add_overlap(chunks, overlap_words=30):
    """Post-process any chunk list to carry the previous chunk's tail forward."""
    out = []
    for i, c in enumerate(chunks):
        if i == 0:
            out.append(c)
        else:
            tail = " ".join(chunks[i - 1].split()[-overlap_words:])
            out.append(tail + " " + c)
    return out


def sentence_split(text):
    parts = re.split(r'(?<=[.!?”"])\s+', text.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


def semantic_chunk(text, max_words=200, min_words=40, pct=25):
    """Split where the topic shifts: embed each sentence, and start a new chunk
    when a sentence is dissimilar to the one before it (a similarity in the
    bottom `pct` percentile) - or when the chunk gets too big."""
    sents = sentence_split(text)
    embs = EF(sents)

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb + 1e-9)

    sims = [cos(embs[i], embs[i - 1]) for i in range(1, len(sents))]
    cut = sorted(sims)[max(0, int(len(sims) * pct / 100) - 1)]  # bottom-pct similarity

    chunks, cur, cur_w = [], [sents[0]], len(sents[0].split())
    for i in range(1, len(sents)):
        w = len(sents[i].split())
        shift = sims[i - 1] <= cut
        if (shift and cur_w >= min_words) or cur_w + w > max_words:
            chunks.append(" ".join(cur)); cur, cur_w = [sents[i]], w
        else:
            cur.append(sents[i]); cur_w += w
    chunks.append(" ".join(cur))
    return chunks


def avg_w(chunks):
    return sum(len(c.split()) for c in chunks) / len(chunks)


# ── retrieval helpers ────────────────────────────────────────────────────────

def hit_at(docs, gps, k):
    gpn = [norm(g) for g in gps]
    return any(any(g in norm(d) for g in gpn) for d in docs[:k])


def build(client, name, chunks):
    try:
        client.delete_collection(name)
    except Exception:
        pass
    coll = client.create_collection(name, embedding_function=EF,
                                    metadata={"hnsw:space": "cosine"})
    coll.add(ids=[f"{name}-{i}" for i in range(len(chunks))], documents=chunks)
    return coll


# ── BM25 (keyword) + dense fusion ────────────────────────────────────────────

def bm25_rank(query, chunks, k1=1.5, b=0.75):
    tok = lambda s: re.findall(r"[a-z']+", s.lower())
    docs = [tok(c) for c in chunks]
    N = len(docs); avgdl = sum(len(d) for d in docs) / N
    df = Counter()
    for d in docs:
        df.update(set(d))
    idf = {w: math.log(1 + (N - f + 0.5) / (f + 0.5)) for w, f in df.items()}
    q = tok(query)
    scores = []
    for d in docs:
        tf = Counter(d); dl = len(d); s = 0.0
        for w in q:
            if w in tf:
                s += idf.get(w, 0) * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    order = sorted(range(N), key=lambda i: -scores[i])
    return {idx: r for r, idx in enumerate(order, 1)}  # chunk idx -> bm25 rank


def main():
    text = task.DOC_PATH.read_text(encoding="utf-8")
    ts = [q for q in json.loads((DAY_DIR / "test_set.json").read_text()) if q["answerable"]]
    n = len(ts)

    canon = chromadb.PersistentClient(path=str(task.CHROMA_DIR))
    expl = chromadb.PersistentClient(path=str(DAY_DIR / "explore_db"))

    # existing three + four new ones
    print("Building indexes...")
    fixed_chunks = task.chunk_fixed(text)
    strat_chunks = {
        "recursive+ovlp": add_overlap(task.chunk_recursive(text)),
        "large (300w)": task.chunk_fixed(text, size=300),
        "small (75w)": task.chunk_fixed(text, size=75),
        "semantic": semantic_chunk(text),
    }
    colls = {name: canon.get_collection(name, embedding_function=EF)
             for name in ["fixed", "overlapping", "recursive"]}
    for name, ch in strat_chunks.items():
        print(f"  {name:<16} {len(ch):>3} chunks, avg {avg_w(ch):5.1f}w")
        colls[name] = build(expl, name.replace(" ", "_").replace("(", "").replace(")", "").replace("+", "_"), ch)

    order = ["fixed", "overlapping", "recursive", "recursive+ovlp",
             "large (300w)", "small (75w)", "semantic"]

    # retrieve top-10 for every strategy/question
    retr = {name: {} for name in order}
    for name in order:
        for q in ts:
            retr[name][q["id"]] = colls[name].query(query_texts=[q["question"]], n_results=10)["documents"][0]

    # ── Part A: hit@5 per strategy ──
    print("\n=== Part A: hit-rate@5 for every chunking strategy ===")
    for name in order:
        h = sum(hit_at(retr[name][q["id"]], q["gold_phrases"], 5) for q in ts)
        print(f"  {name:<16} {h}/{n}  ({h/n:.0%})")

    # ── Part B: best-case union (an oracle that picks the best strategy per Q) ──
    print("\n=== Part B: UNION ceiling (answer in ANY strategy's top-5) ===")
    for combo in [["fixed", "recursive"], order]:
        u = sum(any(hit_at(retr[nm][q["id"]], q["gold_phrases"], 5) for nm in combo) for q in ts)
        print(f"  union of {len(combo)} ({', '.join(combo) if len(combo)<=2 else 'all'}): {u}/{n} ({u/n:.0%})")

    # ── Part C1: hit@k curve for plain fixed ──
    print("\n=== Part C: hit-rate@k for fixed (raising k trivially lifts the number) ===")
    for k in (1, 3, 5, 10, 20):
        # need >10 for k=20: re-query
        docs20 = {q["id"]: colls["fixed"].query(query_texts=[q["question"]], n_results=k)["documents"][0] for q in ts} if k > 10 else None
        h = sum(hit_at(docs20[q["id"]] if docs20 else retr["fixed"][q["id"]], q["gold_phrases"], k) for q in ts)
        print(f"  @{k:<3} {h}/{n} ({h/n:.0%})")

    # ── Part C2: hybrid BM25 + dense (RRF) on the fixed chunks ──
    # NOTE: this HURTS here. BM25 matches QUERY words to DOC words, but our
    # questions ("what do the family do after his death") do not contain the
    # answer's distinctive keywords ("tram", "countryside"). So BM25 ranks
    # common-word chunks (gregor/family) highly and equal-weight fusion lets that
    # noise override good dense results. Hybrid only helps when the question
    # itself carries the answer's rare keywords.
    print("\n=== Part C: HYBRID (BM25 + dense, reciprocal-rank-fusion) on fixed chunks ===")
    got = canon.get_collection("fixed", embedding_function=EF).get()
    # map chunk-id -> index -> text
    idx_text = {int(i.split("-")[-1]): d for i, d in zip(got["ids"], got["documents"])}
    fixed_texts = [idx_text[i] for i in range(len(idx_text))]

    hyb = dense_only = 0
    rescued = []
    for q in ts:
        # dense ranking over all fixed chunks
        dres = colls["fixed"].query(query_texts=[q["question"]], n_results=len(fixed_texts))
        dense_rank = {int(cid.split("-")[-1]): r for r, cid in enumerate(dres["ids"][0], 1)}
        bm = bm25_rank(q["question"], fixed_texts)
        fused = sorted(range(len(fixed_texts)),
                       key=lambda i: -(1 / (60 + dense_rank[i]) + 1 / (60 + bm[i])))
        top5_docs = [fixed_texts[i] for i in fused[:5]]
        h = hit_at(top5_docs, q["gold_phrases"], 5)
        d = hit_at([fixed_texts[i] for i in sorted(range(len(fixed_texts)), key=lambda i: dense_rank[i])[:5]],
                   q["gold_phrases"], 5)
        hyb += h; dense_only += d
        if h and not d:
            rescued.append(q["id"])
    print(f"  dense-only fixed: {dense_only}/{n} ({dense_only/n:.0%})")
    print(f"  hybrid  fixed:    {hyb}/{n} ({hyb/n:.0%})   rescued by keywords: {rescued}")

    # ── Part C3: HyDE query expansion (LLM drafts a hypothetical answer) ──
    # The textbook fix for a query<->answer vocabulary gap. Here it BACKFIRES:
    # a small 3B model hallucinates the hypothetical answer, so retrieval is
    # pulled toward wrong content. Query expansion is only as good as the model.
    print("\n=== Part C: HyDE (llama3.2:3b drafts a hypothetical answer, then retrieve) ===")

    def hyde(question):
        p = ("In one short sentence, state a plausible factual answer to this "
             "question about Kafka's The Metamorphosis. Answer only, no preamble.\n"
             f"Q: {question}")
        r = ollama.chat(model="llama3.2:3b", messages=[{"role": "user", "content": p}],
                        options={"temperature": 0})
        return r["message"]["content"].strip()

    d_ok = h_ok = 0
    h_rescued = []
    for q in ts:
        d = colls["fixed"].query(query_texts=[q["question"]], n_results=5)["documents"][0]
        draft = hyde(q["question"])
        hd = colls["fixed"].query(query_texts=[q["question"] + " " + draft], n_results=5)["documents"][0]
        dh, hh = hit_at(d, q["gold_phrases"], 5), hit_at(hd, q["gold_phrases"], 5)
        d_ok += dh; h_ok += hh
        if hh and not dh:
            h_rescued.append(q["id"])
    print(f"  dense-only: {d_ok}/{n} ({d_ok/n:.0%})")
    print(f"  HyDE:       {h_ok}/{n} ({h_ok/n:.0%})   rescued: {h_rescued}")


if __name__ == "__main__":
    main()
