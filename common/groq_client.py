import os
import re
import time
from dotenv import load_dotenv
from groq import Groq, RateLimitError

load_dotenv()

RETRY_WAIT_RE = re.compile(r"try again in (?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?")


def get_client():
    api_key = os.environ["GROQ_API_KEY"]
    return Groq(api_key=api_key)


def parse_retry_seconds(message, default=5.0):
    match = RETRY_WAIT_RE.search(message)
    if not match:
        return default
    minutes, seconds, millis = match.groups()
    total = (float(minutes or 0) * 60) + float(seconds or 0) + (float(millis or 0) / 1000)
    return total if total > 0 else default


def ask(prompt, model="llama-3.3-70b-versatile", temperature=0.7, system=None, max_retries=3, max_wait_seconds=60, response_format=None):
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # response_format={"type": "json_object"} turns on Groq's JSON mode, which
    # guarantees syntactically valid JSON (but NOT that it matches your schema).
    kwargs = {"model": model, "messages": messages, "temperature": temperature}
    if response_format is not None:
        kwargs["response_format"] = response_format

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except RateLimitError as e:
            wait = parse_retry_seconds(str(e))
            if attempt == max_retries or wait > max_wait_seconds:
                raise
            print(f"  rate limited, waiting {wait:.1f}s before retry {attempt + 1}/{max_retries}...")
            time.sleep(wait)
