import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()


def get_client():
    api_key = os.environ["GROQ_API_KEY"]
    return Groq(api_key=api_key)


def ask(prompt, model="llama-3.3-70b-versatile"):
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
