"""
Week 3 - Day 3 (Course Day 13) - LangGraph agent + Neo4j knowledge graph.

This uses BOTH KG-related tools together, and shows the crucial distinction:
  * LangGraph  = a CONTROL-FLOW graph (nodes = agent steps, edges = transitions).
                 It orchestrates HOW the agent moves.
  * Neo4j      = the KNOWLEDGE graph (facts + relationships). It stores WHAT is true.

The LangGraph agent has one tool that runs a Cypher query against Neo4j. So the
agent's control-flow graph *calls into* the knowledge graph — the standard pattern
(the KG is a tool the agent uses, not the agent framework itself).

The compiled LangGraph looks like the canonical ReAct loop:
    START -> agent -> (tools -> agent)* -> END
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

sys.path.insert(0, str(Path(__file__).parent))
import kg_neo4j

load_dotenv()


# ── the tool: a Cypher query against the Neo4j knowledge graph ──
@tool
def cities_with_both(cat_a: str, price_a: str, cat_b: str) -> list:
    """Return cities that have BOTH a `price_a` `cat_a` place AND a `cat_b` place.
    cat_a/cat_b in {food, art, sightseeing}; price_a in {cheap, medium, expensive}."""
    return kg_neo4j.cities_with_both(cat_a, price_a, cat_b)


llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0).bind_tools([cities_with_both])


def agent_node(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


# ── build the LangGraph control-flow graph ──
builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode([cities_with_both]))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)   # agent -> tools if tool_calls, else END
builder.add_edge("tools", "agent")
graph = builder.compile()


if __name__ == "__main__":
    kg_neo4j.load_from_store()          # make sure Neo4j is populated

    print("=== LangGraph control-flow graph (mermaid) ===")
    print(graph.get_graph().draw_mermaid())

    q = "Which of your cities have both cheap food and art to see?"
    print(f"\n=== Run: {q} ===")
    result = graph.invoke({"messages": [("user", q)]})
    for m in result["messages"]:
        role = m.type
        if getattr(m, "tool_calls", None):
            print(f"  [agent] -> tool_call: {m.tool_calls[0]['name']}({m.tool_calls[0]['args']})")
        elif role == "tool":
            print(f"  [neo4j tool result] {m.content}")
        elif role == "ai" and m.content:
            print(f"  [agent final answer] {m.content[:200]}")
    kg_neo4j.close()
