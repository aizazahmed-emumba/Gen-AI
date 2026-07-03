import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from common.groq_client import ask
import tiktoken

# ─── PART 1: Temperature Comparison ──────────────────────────────────────────

PROMPTS = [
    "What is 2 + 2? Answer in one word.",
    "Write a haiku about the ocean.",
    "Explain quantum entanglement in exactly one sentence.",
    "Tell me a short joke.",
    "What is the capital of France? Answer in one word.",
    "Write the opening line of a story about a lost robot.",
    "Give me three words that describe summer.",
    "Describe the color blue without using the word 'blue'.",
    "Translate 'hello, how are you?' into German and Urdu.",
    "If you could be any animal, what would you be and why? (2 sentences max)",
]

TEMPERATURES = [0.0, 0.7, 1.0]


def run_temperature_comparison():
    print("\n" + "=" * 70)
    print("PART 1 — TEMPERATURE COMPARISON")
    print("=" * 70)

    results = {}

    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n[Prompt {i}] {prompt}")
        print("-" * 60)
        results[prompt] = {}
        for temp in TEMPERATURES:
            response = ask(prompt, temperature=temp)
            results[prompt][temp] = response
            label = f"temp={temp}"
            print(f"  {label:<10}: {response.strip()[:200]}")

    return results


# ─── PART 2: Tokenizer Comparison ────────────────────────────────────────────

# 30 strings: code, Urdu/Deutsch mix, emojis, long URLs, JSON
STRINGS = [
    # ── Code (6) ──
    "def fibonacci(n): return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)",
    "SELECT * FROM users WHERE email LIKE '%@example.com' ORDER BY created_at DESC;",
    "const fetchData = async (url) => { const res = await fetch(url); return res.json(); };",
    "public static void main(String[] args) { System.out.println(\"Hello World\"); }",
    "git commit -m 'fix: resolve null pointer exception in auth middleware'",
    "docker run -d -p 8080:80 --name my-app -e DATABASE_URL=postgres://user:pass@db/mydb nginx:latest",

    # ── Urdu (4) ──
    "آج کا موسم بہت اچھا ہے",
    "میں پاکستان میں رہتا ہوں اور مجھے اردو بولنا پسند ہے",
    "مصنوعی ذہانت کا مستقبل بہت روشن ہے",
    "یہ ایک مشین لرننگ کا تجربہ ہے جو ٹوکنائزیشن کو جانچتا ہے",

    # ── German (4) ──
    "Künstliche Intelligenz verändert die Welt grundlegend.",
    "Das Wetter heute ist wunderschön und sonnig.",
    "Ich lerne maschinelles Lernen und natürliche Sprachverarbeitung.",
    "Donaudampfschifffahrtsgesellschaft ist ein sehr langes deutsches Wort.",

    # ── Urdu + German mix (2) ──
    "میں Künstliche Intelligenz سیکھ رہا ہوں",
    "Das ist sehr gut! یہ بہت اچھا ہے!",

    # ── Emojis (4) ──
    "🎉🎊🥳 Happy Birthday! 🎂🕯️🎁",
    "🚀🌍🌑 The moon landing was 🏆 historic 💫",
    "😂🤣😅 I can't stop laughing 😭😂",
    "🐍💻🔥 Python is awesome! 🚀✨🎯",

    # ── Long URLs (4) ──
    "https://www.example.com/products/category/electronics/laptops?brand=apple&model=macbook-pro&year=2024&color=space-gray&storage=1tb#reviews",
    "https://api.github.com/repos/owner/repository-name/issues?state=open&labels=bug,enhancement&per_page=100&page=1",
    "https://docs.python.org/3/library/functions.html#built-in-functions",
    "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster-than-processing-an-unsorted-array",

    # ── JSON (4) ──
    '{"name":"Ali","age":25,"city":"Islamabad","skills":["Python","ML","NLP"]}',
    '{"status":200,"message":"success","data":{"users":[{"id":1,"email":"a@b.com"}]}}',
    '{"model":"llama-3","temperature":0.7,"max_tokens":1024,"messages":[{"role":"user","content":"Hello"}]}',
    '{"error":null,"result":{"embedding":[0.123,-0.456,0.789],"token_count":42}}',

    # ── Misc / edge cases (2) ──
    "     ",  # whitespace only
    "1234567890 !@#$%^&*() abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ",
]


def run_tokenizer_comparison():
    print("\n" + "=" * 70)
    print("PART 2 — TOKENIZER COMPARISON")
    print("  Model A: cl100k_base  (GPT-4 / GPT-3.5 BPE — ~100k vocab)")
    print("  Model B: gpt2         (GPT-2 BPE — ~50k vocab)")
    print("=" * 70)

    enc_a = tiktoken.get_encoding("cl100k_base")
    enc_b = tiktoken.get_encoding("gpt2")

    rows = []
    print(f"\n{'#':<4} {'cl100k':>8} {'gpt2':>6} {'diff':>6}  String (truncated to 60 chars)")
    print("-" * 90)

    for i, s in enumerate(STRINGS, 1):
        count_a = len(enc_a.encode(s))
        count_b = len(enc_b.encode(s))
        diff = count_b - count_a
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        preview = s.replace("\n", " ")[:60]
        print(f"{i:<4} {count_a:>8} {count_b:>6} {diff_str:>6}  {preview}")
        rows.append({
            "index": i,
            "string": s,
            "cl100k_base": count_a,
            "gpt2": count_b,
            "diff_gpt2_minus_cl100k": diff,
        })

    return rows



if __name__ == "__main__":
    temp_results = run_temperature_comparison()
    token_rows = run_tokenizer_comparison()

    # Save raw results for the report
    out_path = Path(__file__).parent / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"temperature_results": {str(k): v for k, v in temp_results.items()},
             "tokenizer_rows": token_rows},
            f, ensure_ascii=False, indent=2,
        )
    print(f"\nRaw results saved to {out_path}")
