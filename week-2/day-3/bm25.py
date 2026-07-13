"""
Week 2 - Day 3 (Course Day 8) - BM25 lexical search, from scratch.

Vector search matches MEANING. BM25 matches WORDS. They fail on opposite inputs,
which is the entire reason hybrid retrieval exists — so it's worth understanding
BM25 as an algorithm, not a black box.

THE INTUITION (three ideas stacked):
  1. Term frequency (TF): a chunk that says "wireless" 5 times is more about
     wireless than one that says it once. BUT with diminishing returns — the 5th
     mention adds less than the 1st. (A raw count would let one spammy word win.)
  2. Inverse document frequency (IDF): a chunk matching a RARE word ("harpooneer")
     tells us far more than one matching a common word ("the", "system"). Rare
     hits are weighted up, common hits down.
  3. Length normalization: a 1000-word chunk naturally contains more of every word
     than a 100-word chunk. We discount long chunks so they don't win by size.

Okapi BM25 is just those three ideas in one formula:

    score(D, query) = Σ_t  IDF(t) · [ f(t,D)·(k1+1) ] / [ f(t,D) + k1·(1 - b + b·|D|/avgdl) ]

    f(t,D) = count of term t in chunk D
    |D|    = length of D in tokens ;  avgdl = average chunk length
    k1     = TF saturation knob (~1.5): how fast extra repeats stop helping
    b      = length-normalization knob (~0.75): how hard to punish long chunks

This is exactly what Elasticsearch / Lucene use under the hood.
"""

import math
import re
from collections import Counter

K1 = 1.5
B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    """Lowercase, split on non-alphanumerics. 'AC-2' -> ['ac','2'] so a query for
    'AC-2' still lexically matches the heading — vector search would blur that."""
    return _TOKEN_RE.findall(text.lower())


class BM25:
    def __init__(self, ids, documents):
        self.ids = ids
        self.docs_tokens = [tokenize(d) for d in documents]
        self.doc_len = [len(t) for t in self.docs_tokens]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.N = len(documents)

        # term frequency per doc, and document frequency per term (how many docs contain it)
        self.tf = [Counter(toks) for toks in self.docs_tokens]
        df = Counter()
        for toks in self.docs_tokens:
            for term in set(toks):
                df[term] += 1
        # precompute IDF for every term. The +1 inside the log keeps IDF >= 0 even
        # for terms in more than half the corpus (the "BM25+" safeguard).
        self.idf = {
            term: math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for term, n in df.items()
        }

    def search(self, query, k=20):
        q_terms = tokenize(query)
        scores = []
        for i in range(self.N):
            tf_i, dl = self.tf[i], self.doc_len[i]
            s = 0.0
            for t in q_terms:
                if t not in tf_i:
                    continue
                f = tf_i[t]
                denom = f + K1 * (1 - B + B * dl / self.avgdl)
                s += self.idf.get(t, 0.0) * (f * (K1 + 1)) / denom
            if s > 0:
                scores.append((self.ids[i], s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]      # list of (chunk_id, bm25_score)
