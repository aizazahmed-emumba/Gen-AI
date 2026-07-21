"""
Week 3 - Day 3 (Course Day 13) - minimal KG-in-an-agent-flow demo.

Wires the knowledge graph in as a TOOL. The LLM calls `graph_cities_with_both`
to answer a MULTI-HOP question grounded in the graph — something a vector-RAG tool
could not answer, because it's a relational join, not a similarity search.

This is the "KG for grounding/control" pattern: the agent's answer is backed by a
deterministic graph query, not by the model's memory.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.groq_client import get_client

import kg

MODEL = "openai/gpt-oss-120b"
_G = kg.build_graph()

TOOLS = [{"type": "function", "function": {
    "name": "graph_cities_with_both",
    "description": "Query the travel knowledge graph for cities that contain BOTH a "
                   "place of category `cat_a` at `price_a`, AND a place of category "
                   "`cat_b`. Use for relational/multi-hop questions.",
    "parameters": {"type": "object", "properties": {
        "cat_a": {"type": "string", "enum": ["food", "art", "sightseeing"]},
        "price_a": {"type": "string", "enum": ["cheap", "medium", "expensive"]},
        "cat_b": {"type": "string", "enum": ["food", "art", "sightseeing"]},
    }, "required": ["cat_a", "price_a", "cat_b"]},
}}]


def run(query):
    client = get_client()
    messages = [{"role": "system", "content": "You answer travel questions using the "
                 "knowledge-graph tool for anything relational. Answer only from tool results."},
                {"role": "user", "content": query}]
    r = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS,
                                       tool_choice="auto", temperature=0)
    msg = r.choices[0].message
    if not msg.tool_calls:
        return f"[no tool] {msg.content}"

    tc = msg.tool_calls[0]
    args = json.loads(tc.function.arguments)
    result = kg.cities_with_both(_G, args["cat_a"], args["price_a"], args["cat_b"])
    print(f"  -> agent called graph_cities_with_both({args}) => {result}")

    messages.append({"role": "assistant", "content": "", "tool_calls": [tc.model_dump()]})
    messages.append({"role": "tool", "tool_call_id": tc.id,
                     "name": tc.function.name, "content": json.dumps({"cities": result})})
    r2 = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    return r2.choices[0].message.content


if __name__ == "__main__":
    q = "Which of your cities have both cheap food and art to see?"
    print("Q:", q)
    print("A:", run(q))
