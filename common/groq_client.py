import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()


def get_client():
    api_key = os.environ["GROQ_API_KEY"]
    return Groq(api_key=api_key)


def ask(prompt, model="llama-3.3-70b-versatile", temperature=0.7, system=None):
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content
