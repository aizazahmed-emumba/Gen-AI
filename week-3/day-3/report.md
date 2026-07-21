# Week 3 – Day 3 Report (Course Day 13) — Knowledge Graphs in Agent-Based GenAI

## Where knowledge graphs fit the agent spectrum

Everything we built before retrieves by **similarity** (vector search). A knowledge
graph retrieves by **explicit typed relationships**. It plays three roles alongside an
agent:

| Role                     | What the KG does                                          | Our hands-on example                                                               |
| ------------------------ | --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **Grounding**            | answer from verified entities/relations, not fuzzy chunks | `places(city, category, price)` returns real place nodes                           |
| **Reasoning**            | multi-hop joins across facts (similarity search can't)    | "cities with **both** cheap food **and** art" → Berlin, Amsterdam, Rome, Barcelona |
| **Validation / control** | deterministically check a claim; constrain allowed paths  | `fact_exists("Museums (Berlin)", "Paris")` → **False**                             |

**The core distinction:** vector RAG finds text that _sounds_ related; a KG encodes
_how facts connect_. Multi-hop relational questions and fact-validation are where KGs win.

## The three types of KG tooling (what the task asked to explore)

### 1. Graph databases — **Neo4j** (also Memgraph, Kùzu)

- **Problem it solves:** store and query large property graphs (`nodes -[edges]-> nodes`)
  with a real query language (**Cypher**), plus graph algorithms and, increasingly, a
  vector index for hybrid search.
- **LLM/agent integration:** the `neo4j` driver + connectors in LangChain/LlamaIndex; two
  patterns — (a) **text2cypher** (LLM writes the Cypher), or (b) expose fixed graph queries
  as **agent tools** (what we did in `kg_agent.py`).
- **Reasoning / validation / control:** ✅ reasoning (multi-hop, GDS algorithms),
  ✅ validation (uniqueness/existence constraints, deterministic lookups), ~ control (schema).
- _Memgraph_ = in-memory, real-time/streaming, Cypher-compatible. _Kùzu_ = **embedded**
  (no server, like SQLite for graphs) — great for local apps.

### 2. KG-aware RAG frameworks — **LlamaIndex Property Graph Index** (also Microsoft **GraphRAG**)

- **Problem it solves:** _automatically build_ a KG from unstructured documents (an LLM
  extracts entity→relation triples) and retrieve over it — so you get KG reasoning without
  hand-modeling a schema. GraphRAG additionally clusters the graph for "global" questions.
- **LLM/agent integration:** native; combines **graph + vector** retrieval (hybrid) out of
  the box; can persist to Neo4j underneath.
- **Reasoning / validation / control:** ~ reasoning (multi-hop retrieval), ✗ validation (the
  LLM-extracted graph is **noisy** — it can hallucinate relations), ✗ tight control.

### 3. Agent frameworks with graph abstractions — **LangGraph**

- **⚠️ Important distinction:** LangGraph's graph is a **control-flow graph** (agent steps
  as nodes, transitions as edges) — **NOT a knowledge graph.** Conflating the two is a
  common beginner mistake. It models _how the agent moves_, not _what it knows_.
- **Problem it solves:** orchestrate stateful, cyclic, multi-step agent workflows with
  checkpointing and human-in-the-loop.
- **Reasoning / validation / control:** ✅✅ **control** (its whole point — deterministic
  agent flow, the "control" corner of the KG spectrum), ~ validation (you add checks as
  nodes). It's the agent's skeleton; a real KG (Neo4j) would be a _tool_ it calls.

## Comparison table

| Tool                                     | Category                             | Purpose & abstraction level                                                         | Ease of integration w/ agents/RAG                                                | Strengths                                                                             | Limitations                                                                           |
| ---------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Neo4j**                                | Graph database                       | Store/query property graphs; **low-level** (you model schema + write Cypher)        | Medium — driver + LangChain/LlamaIndex connectors; expose as tool or text2cypher | Mature, scalable, Cypher + graph algorithms, now hybrid vector too; strong validation | Needs a server (Aura/self-host); Cypher + modeling learning curve; ingestion effort   |
| **LlamaIndex Property Graph / GraphRAG** | KG-aware RAG                         | Auto-extract a KG from text + retrieve; **high-level** (framework builds the graph) | Easy — native LLM, hybrid KG+vector, little code                                 | Turns documents→KG automatically; global reasoning (GraphRAG); low code               | LLM-extracted graph is **noisy/unverifiable**; less control; costs LLM calls to build |
| **LangGraph**                            | Agent framework (control-flow graph) | Orchestrate agent steps as a **stateful graph**; **high-level**                     | Easy — it _is_ the agent runtime                                                 | Robust cyclic/branching flows, state, checkpoints, human-in-loop                      | **Not a knowledge graph**; adds no domain facts; would call a real KG as a tool       |
| _(our hands-on)_ **NetworkX**            | In-memory graph lib                  | Property graph in pure Python; **low-level, no query language**                     | Easy — call as a Python tool                                                     | Zero setup, perfect for teaching multi-hop                                            | In-memory only, no Cypher, doesn't scale/persist                                      |

## Hands-on (what we actually ran)

We built the travel KG (**106 nodes, 196 relationships**) three ways, escalating from a
teaching stub to real infrastructure:

1. **NetworkX** (`kg.py`) — in-memory, zero setup, for learning the traversal.
2. **Neo4j** (`kg_neo4j.py`) — a **real graph database** in Docker, loaded and queried in
   **actual Cypher** (`docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/… neo4j:5`).
3. **LangGraph + Neo4j** (`kg_langgraph.py`) — a LangGraph agent whose tool runs a Cypher
   query against Neo4j — **both KG-tool categories together.**

Graph model: `(:Place {price}) -[:LOCATED_IN]-> (:City)` and `(:Place) -[:OF_CATEGORY]-> (:Category)`.

| Query (real Cypher on Neo4j) | Result | Point |
| --- | --- | --- |
| single-hop: cheap food in Rome | Pizza, Gelato, … | grounding |
| **multi-hop**: cities with **both** cheap food **and** art | **Berlin, Amsterdam, Rome, Barcelona** (Paris excluded — no cheap-food node) | reasoning vector RAG can't do |
| validation: `Museums(Berlin)` located in Paris? | **False** | deterministic fact-check |
| **LangGraph agent** (`kg_langgraph.py`): "cities with both cheap food and art?" | agent → `tools` node runs Cypher on Neo4j → answered from the result | KG-as-tool inside an agent graph |

**The two graphs, side by side (from the actual run).** LangGraph printed its own
*control-flow* graph — proof it is not a knowledge graph:
```
START --> agent
agent -.-> tools      (if the LLM emitted a tool_call)
agent -.-> END        (otherwise)
tools --> agent
```
That graph decides *how the agent moves*; the **Neo4j** graph (`Place→City`, `Place→Category`)
stores *what is true*. The agent's `tools` node calls Cypher on Neo4j — the KG is a **tool**,
LangGraph is the **runtime**.

## Summary — when KGs make sense, and when they're overkill

**Knowledge graphs make sense when:**

- Questions are **relational / multi-hop** ("X connected to Y that also relates to Z") — the
  join our vector store couldn't do.
- You need **validation / grounding against ground truth** (check an LLM claim; enforce that
  only real entities/relations are used) — critical for high-stakes domains (finance,
  medical, compliance).
- The domain has **stable, well-defined entities and relationships** worth modeling once
  (org charts, product catalogs, supply chains, citations).
- You want **explainable** retrieval (a path through the graph _is_ the reason).

**They're overkill when:**

- Questions are **semantic/fuzzy** ("something _like_ impressionism") — that's vector RAG's job.
- The data is **unstructured prose** with no clear entities/relations, and building/maintaining
  the graph costs more than it returns (our travel corpus is borderline — vector RAG already
  handled most single-city questions).
- It's a **small or one-off** project — the modeling + infrastructure (a graph server, schema,
  ingestion, keeping it fresh) outweighs the benefit.
- The KG would be **LLM-extracted and unverified** — then you've added a noisy layer without
  the validation guarantee that is the KG's main reason to exist.

**The rule of thumb:** reach for a KG when the value is in the **relationships and their
correctness**, not just the content. If you only need "find text similar to my question,"
a vector store is simpler and enough. Many strong systems are **hybrid** (GraphRAG): the KG
for structure/validation, vectors for fuzzy recall — the graph is a _tool the agent calls_,
not a replacement for retrieval.

Files: [kg.py](week-3/day-3/kg.py) (NetworkX build/query/validate), [kg_agent.py](week-3/day-3/kg_agent.py) (KG-as-tool, Groq), [kg_neo4j.py](week-3/day-3/kg_neo4j.py) (**real Neo4j + Cypher**), [kg_langgraph.py](week-3/day-3/kg_langgraph.py) (**LangGraph agent → Neo4j tool**).

> Run notes: start Neo4j with `docker run -d --name neo4j-kg -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/testpassword123 neo4j:5` (browser UI at http://localhost:7474), then `python kg_neo4j.py` / `python kg_langgraph.py`. Requires `pip install neo4j langgraph langchain-groq`.
