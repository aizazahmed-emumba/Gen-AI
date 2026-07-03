# Week 1 – Day 1 Report

## Task

1. Run 10 prompts with 3 decoding settings (`temp=0`, `0.7`, `1.0`) and compare outputs.
2. Pick 30 strings (code, Urdu/Deutsch mix, emojis, long URLs, JSON), tokenize using 2 tokenizers (`cl100k_base` and `gpt2`), compare counts.

---

### Temperature Deep-Dive

```
temp = 0   → Greedy decoding. Same output every run (deterministic).
             Best for: factual Q&A, SQL generation, classification.

temp = 0.7 → Balanced sampling. Some variety but stays coherent.
             Best for: chat, summarization, general assistance.

temp = 1.0 → Full stochastic sampling from the raw softmax.
             Best for: creative writing, brainstorming, poetry.
             Risk: hallucinations, repetition loops, incoherence.
```

**Why does temperature change creativity?**
The model computes a probability over all ~32,000–128,000 vocabulary tokens for the next word. At `temp=0` only the top token is chosen. At `temp=1` the raw probabilities are used — a word with 5% probability is sampled 5% of the time, meaning unexpected but valid words occasionally "win". This is what produces creative variation.

---

## Part 1 — Temperature Comparison

### The 10 Prompts

### Observed Outputs (actual run — regenerate with `task.py`)

> **Prompt 1 — "What is 2 + 2? Answer in one word."**
>
> | temp=0 | temp=0.7 | temp=1.0 |
> | ------ | -------- | -------- |
> | Four.  | Four.    | Four.    |
>
> _(Fully deterministic — the token "Four" has ~100% probability here)_

> **Prompt 2 — Haiku about the ocean**
>
> | temp=0                                                                           | temp=0.7                                                                    | temp=1.0                                                               |
> | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
> | Crashing blue waves rise / Salty scent and seaweed dance / Ocean's soothing song | Crashing waves serene / Moonlight dancing on the tide / Ocean's gentle song | Crashing blue waves rise / Gentle foam upon the shore / Serenity's sea |
>
> _(All three start with "Crashing" — the model's default opening is so dominant that even temp=1.0 doesn't escape it. Slight word variation occurs.)_

> **Prompt 4 — Tell me a short joke**
>
> | temp=0                                      | temp=0.7                                    | temp=1.0                                    |
> | ------------------------------------------- | ------------------------------------------- | ------------------------------------------- |
> | What do you call a fake noodle? An impasta. | What do you call a fake noodle? An impasta. | What do you call a fake noodle? An impasta. |
>
> _(Surprise: the "impasta" joke is the same at ALL temperatures. Popular jokes are highly concentrated in training data, so the probability is overwhelmingly peaked — temperature cannot dislodge it.)_

> **Prompt 7 — Give me three words that describe summer**
>
> | temp=0                | temp=0.7              | temp=1.0              |
> | --------------------- | --------------------- | --------------------- |
> | Warm, Sunny, Relaxing | Warm, Sunny, Relaxing | Warm, Sunny, Relaxing |
>
> _(Another complete lock-in. "Warm" and "Sunny" are so strongly associated with summer that even temp=1.0 produces identical output.)_

> **Prompt 10 — If you could be any animal…**
>
> | temp=0                           | temp=0.7                             | temp=1.0                                                  |
> | -------------------------------- | ------------------------------------ | --------------------------------------------------------- |
> | Dolphin (intelligent, social...) | Dolphin (variety of environments...) | **Octopus** (intelligence, adaptability, change color...) |
>
> _(This is the clearest temperature effect: at temp=0 and 0.7 the model picks dolphin — a highly probable "safe" answer. At temp=1.0 it picks octopus, a less common but valid answer that had lower probability mass.)_

### Key Observations

1. **Factual prompts (1, 5, 9)** — identical at all temperatures. When one token has ~100% probability, temperature has zero effect.
2. **Popular creative answers (4, 7)** — also identical at all temperatures. "Impasta" and "Warm/Sunny/Relaxing" are so common in training data that their probability is nearly as deterministic as a fact.
3. **Open-ended creative prompts (10)** — temperature visibly changes output. `temp=0/0.7` → dolphin; `temp=1.0` → octopus. This is the temperature effect working as intended.
4. **Most outputs start the same way** even at high temperature (prompt 6: all three start "As the last remnants of sunlight faded…"). The first few tokens of a response are highly probable; temperature diversity appears later in the generation.
5. **`temp=0` tends to be repetitive** across re-runs (deterministic). `temp=1.0` will give a different answer every call on repeated runs.

### Re-run Reproducibility Check

A second identical run was made to test how stable outputs are across calls. Results (10 prompts × 3 temperatures):

| temp  | Identical | Changed  |
| ----- | --------- | -------- |
| `0.0` | 7/10      | **3/10** |
| `0.7` | 2/10      | 8/10     |
| `1.0` | 3/10      | 7/10     |

6. **`temp=0` is NOT fully deterministic through hosted APIs.** 3 out of 10 prompts gave different responses on the second run despite `temp=0`. The changes were minor (word order swap "Warm, Sunny" → "Sunny, Warm"; synonym swap "color" → "hue") but real. This is caused by distributed GPU inference — floating-point arithmetic is not bit-identical across different hardware runs, so near-tied token probabilities can flip. True reproducibility requires a `seed` parameter, which the Groq API does not currently expose.
7. **`temp=0.7` changed the most (8/10)** — confirming it is the most "live" setting. Some apparent changes at 0.7 were formatting artifacts (extra whitespace, missing period) rather than meaningful content differences.
8. **`temp=1.0` was more stable than `temp=0.7` in this run (7/10 changed).** This can happen when temp=1.0 still lands on the same high-probability answer — randomness doesn't guarantee more variety, it just makes variety _possible_.

---

## Part 2 — Tokenizer Comparison

**Model A:** `cl100k_base` — GPT-4 / GPT-3.5-turbo BPE tokenizer (~100,000 token vocabulary)  
**Model B:** `gpt2` — GPT-2 BPE tokenizer (~50,000 token vocabulary)

### Full Table

| #   | String (truncated)                                         | cl100k |  gpt2 | Δ (gpt2−cl100k) | Category          |
| --- | ---------------------------------------------------------- | -----: | ----: | --------------: | ----------------- |
| 1   | `def fibonacci(n): return n if n <= 1...`                  |     23 |    31 |              +8 | Code – Python     |
| 2   | `SELECT * FROM users WHERE email LIKE...`                  |     18 |    22 |              +4 | Code – SQL        |
| 3   | `const fetchData = async (url) => {...`                    |     21 |    24 |              +3 | Code – JS         |
| 4   | `public static void main(String[] args)...`                |     17 |    20 |              +3 | Code – Java       |
| 5   | `git commit -m 'fix: resolve null pointer...`              |     15 |    16 |              +1 | Code – CLI        |
| 6   | `docker run -d -p 8080:80 --name my-app...`                |     32 |    39 |              +7 | Code – CLI        |
| 7   | `آج کا موسم بہت اچھا ہے`                                   |     24 |    29 |              +5 | Urdu              |
| 8   | `میں پاکستان میں رہتا ہوں...`                              |     49 |    63 |             +14 | Urdu              |
| 9   | `مصنوعی ذہانت کا مستقبل بہت روشن ہے`                       |     32 |    42 |             +10 | Urdu              |
| 10  | `یہ ایک مشین لرننگ کا تجربہ ہے جو ٹوکنائزیشن کو جانچتا ہے` |     54 |    75 |         **+21** | Urdu              |
| 11  | `Künstliche Intelligenz verändert die Welt...`             |     15 |    21 |              +6 | German            |
| 12  | `Das Wetter heute ist wunderschön und sonnig.`             |     14 |    17 |              +3 | German            |
| 13  | `Ich lerne maschinelles Lernen und natürliche...`          |     19 |    25 |              +6 | German            |
| 14  | `Donaudampfschifffahrtsgesellschaft ist ein sehr...`       |     23 |    29 |              +6 | German – compound |
| 15  | `میں Künstliche Intelligenz سیکھ رہا ہوں`                  |     26 |    33 |              +7 | Urdu + German mix |
| 16  | `Das ist sehr gut! یہ بہت اچھا ہے!`                        |     25 |    31 |              +6 | Urdu + German mix |
| 17  | `🎉🎊🥳 Happy Birthday! 🎂🕯️🎁`                            |     22 |    22 |           **0** | Emojis            |
| 18  | `🚀🌍🌑 The moon landing was 🏆 historic 💫`               |     19 |    20 |              +1 | Emojis            |
| 19  | `😂🤣😅 I can't stop laughing 😭😂`                        |     16 |    16 |           **0** | Emojis            |
| 20  | `🐍💻🔥 Python is awesome! 🚀✨🎯`                         |     20 |    21 |              +1 | Emojis            |
| 21  | `https://www.example.com/products/...#reviews`             |     39 |    49 |             +10 | URL – long        |
| 22  | `https://api.github.com/repos/owner/...page=1`             |     29 |    43 |         **+14** | URL – API         |
| 23  | `https://docs.python.org/3/library/...`                    |     14 |    23 |          **+9** | URL – short       |
| 24  | `https://stackoverflow.com/questions/11227809/...`         |     25 |    41 |         **+16** | URL – long        |
| 25  | `{"name":"Ali","age":25,"city":"Islamabad"...}`            |     23 |    25 |              +2 | JSON – simple     |
| 26  | `{"status":200,"message":"success",...}`                   |     26 |    27 |              +1 | JSON – nested     |
| 27  | `{"model":"llama-3","temperature":0.7,...}`                |     31 |    35 |              +4 | JSON – config     |
| 28  | `{"error":null,"result":{"embedding":[0.123...`            |     26 |    28 |              +2 | JSON – embedding  |
| 29  | `     ` (5 spaces)                                         |  **1** | **5** |          **+4** | Whitespace        |
| 30  | `1234567890 !@#$%^&*() abcdef... ABCDEF...`                |     23 |    42 |         **+19** | Mixed ASCII       |

---

## 5 Surprises Explained

### Surprise 1 — Five spaces = 1 token (cl100k) vs 5 tokens (gpt2) _(String #29)_

|                      | cl100k |  gpt2 |
| -------------------- | -----: | ----: |
| `"     "` (5 spaces) |  **1** | **5** |

**Why:** OpenAI retrained `cl100k_base` (released 2023) with explicit awareness of whitespace patterns. Multiple consecutive spaces are extremely common in code indentation and structured data, so the tokenizer learned to merge them into a single token (e.g., `"    "` = 1 indent token). GPT-2's vocabulary (2019) predates this optimization and treats each space as an individual token. This means GPT-2-era models "waste" context window on indentation — a 200-line Python file with 4-space indentation can cost hundreds of extra tokens.

---

### Surprise 2 — Urdu string #10 costs 54 tokens just in cl100k _(String #10)_

|                                                            | cl100k |   gpt2 |
| ---------------------------------------------------------- | -----: | -----: |
| `یہ ایک مشین لرننگ کا تجربہ ہے جو ٹوکنائزیشن کو جانچتا ہے` | **54** | **75** |

**Why:** The Urdu sentence has 11 words but costs 54–75 tokens. BPE tokenizers learn subword units from their training corpus. Both `cl100k_base` and `gpt2` were trained on predominantly English web text. Urdu (written in Nastaliq/Arabic script) is rare in those corpora. The tokenizer falls back to byte-level encoding for unfamiliar character sequences — each UTF-8 byte becomes its own token. A single Urdu character like `ٹ` may occupy 2 bytes in UTF-8, becoming 2 tokens. This is why chatting in Urdu with GPT-4 costs 4–6× more than the equivalent English message.

---

### Surprise 3 — Emojis are tokenized identically by both tokenizers _(Strings #17, #19)_

|                                     | cl100k | gpt2 |
| ----------------------------------- | -----: | ---: |
| `🎉🎊🥳 Happy Birthday! 🎂🕯️🎁`     |     22 |   22 |
| `😂🤣😅 I can't stop laughing 😭😂` |     16 |   16 |

**Why:** You would expect the newer `cl100k_base` to handle emojis better — but the counts are identical. Emojis (4-byte UTF-8) are so uniformly rare across all pre-2023 web text that neither tokenizer learned to merge them into compact vocabulary entries. Both fall back to byte-level representation, producing the same token count. The "improvement" in cl100k over gpt2 is concentrated in English subwords, code, and whitespace — not emoji sequences.

---

### Surprise 4 — URLs are massively cheaper in cl100k than gpt2 _(Strings #22–24)_

|                                                           | cl100k |          gpt2 |
| --------------------------------------------------------- | -----: | ------------: |
| `https://stackoverflow.com/questions/11227809/why-is-...` |     25 | **41** (+64%) |
| `https://api.github.com/repos/owner/repository-name/...`  |     29 | **43** (+48%) |
| `https://docs.python.org/3/library/functions.html#...`    |     14 | **23** (+64%) |

**Why:** URL paths like `/why-is-processing-a-sorted-array-faster-than` contain common English words separated by hyphens. `cl100k_base` has a larger vocabulary that includes multi-character tokens for common URL fragments (`https`, `://`, `/questions/`, common domain names). GPT-2 splits these more aggressively into shorter subwords. The impact is real: web scraping pipelines and RAG systems that process many URLs use significantly fewer context tokens with modern tokenizers.

---

### Surprise 5 — cl100k ALWAYS wins (all 30 diffs are ≥ 0) _(All strings)_

**Why:** You might expect a trade-off — maybe gpt2 is better at some things, cl100k at others. But across all 30 strings, `cl100k_base` uses equal or fewer tokens than `gpt2` for every single string. This is not an accident. A larger BPE vocabulary (100k vs 50k) means longer subword sequences can be represented as a single token. The cl100k tokenizer was also retrained on a much more diverse corpus (code, multiple languages, structured data) and used BPE with better merging rules. **A larger vocabulary is strictly better for compression as long as the tokenizer was trained on diverse data.** The trade-off is embedding table size (100k × d_model parameters), which is small compared to total model size.

---

## Approach

**Part 1 (Temperature):**

- Used Groq API with `llama-3.3-70b-versatile` model
- Ran each of 10 prompts at `temp ∈ {0.0, 0.7, 1.0}` — 30 total API calls
- Compared outputs side-by-side in the terminal; saved raw results to `results.json`

**Part 2 (Tokenizers):**

- Used `tiktoken` library (pip install tiktoken)
- Tokenizer A: `cl100k_base` — GPT-4 / GPT-3.5-turbo encoding (~100k vocab, BPE)
- Tokenizer B: `gpt2` — GPT-2 encoding (~50k vocab, BPE)
- Ran 30 strings through both encoders; saved raw counts to `tokenizer_results.json`

---

## Notes / Learnings

1. **Temperature ≠ randomness knob on facts.** When one token has 99.9% probability (e.g., "Paris" after "capital of France is"), temperature barely changes the output. It only matters when the probability distribution is flat.

2. **Token cost is not proportional to character count.** A 5-space string costs 1 token in cl100k; a 5-character Urdu word may cost 10+ tokens. This matters for billing and context window planning.

3. **Tokenizers are language-biased.** Both BPE tokenizers encode English much more compactly than Urdu because English dominated their training corpus. This is a form of structural bias — non-English users "pay more" per idea in terms of tokens.

4. **BPE vocabulary size is a design decision with real trade-offs.** Larger vocab → fewer tokens per string → cheaper inference + more context per window. But larger vocab → larger embedding + unembedding matrices → more memory at load time.

5. **cl100k vs gpt2 is the difference between 2019 and 2023 tokenizer engineering.** The improvements are not random — they reflect deliberate decisions to train on code, structured data, and non-English text.
