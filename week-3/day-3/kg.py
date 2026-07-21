"""
Week 3 - Day 3 (Course Day 13) - Knowledge graphs in agent systems.

kg.py — build a small travel KNOWLEDGE GRAPH from our real Day-5 data and query it
by RELATIONSHIP (not similarity). We use NetworkX (in-memory property graph); in
production you'd use Neo4j / Kùzu / Memgraph and write Cypher — the equivalent
Cypher is shown in each query's docstring so you learn the real language too.

THE GRAPH (property-graph model — nodes + typed edges + attributes):
    (:Place {name, price})  -[:LOCATED_IN]->  (:City {name})
    (:Place {name, price})  -[:OF_CATEGORY]-> (:Category {name})

WHY A GRAPH AND NOT JUST VECTORS: vector search finds chunks that are *similar*.
A graph answers questions about *relationships between facts* — especially
MULTI-HOP joins ("cities that have BOTH cheap food AND an art museum") that
similarity search simply cannot express. That's grounding + control, not vibes.
"""

import sys
from pathlib import Path

import networkx as nx

# reuse the Day-5 travel store as the source of real entities/relations
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "week-2" / "day-5"))
import store as t_store


def build_graph():
    """Load places from the Qdrant store and turn their metadata into a graph.
    Each chunk becomes a :Place linked to its :City and :Category."""
    _, meta = t_store.load(), t_store.load()  # ensure loaded
    client = t_store.load()
    points, _ = client.scroll(collection_name="travel", limit=10000, with_payload=True)

    g = nx.DiGraph()
    seen = set()
    for p in points:
        pl = p.payload
        city, cat, price = pl["city"], pl["category"], pl["price_level"]
        name = f"{pl['title']} ({city})"
        # de-dup identical place nodes (many chunks share a section title)
        if name in seen:
            continue
        seen.add(name)
        g.add_node(city, type="city")
        g.add_node(cat, type="category")
        g.add_node(name, type="place", price=price, city=city, category=cat)
        g.add_edge(name, city, rel="LOCATED_IN")
        g.add_edge(name, cat, rel="OF_CATEGORY")
    return g


# ─────────────────────────────────────────────────────────────────────────────
# QUERIES — by relationship, not similarity
# ─────────────────────────────────────────────────────────────────────────────

def places(g, city=None, category=None, price=None):
    """Single-hop filter over :Place nodes.
    Cypher:
      MATCH (p:Place)-[:LOCATED_IN]->(c:City), (p)-[:OF_CATEGORY]->(cat:Category)
      WHERE c.name=$city AND cat.name=$category AND p.price=$price
      RETURN p.name
    """
    out = []
    for n, d in g.nodes(data=True):
        if d.get("type") != "place":
            continue
        if city and d["city"] != city:
            continue
        if category and d["category"] != category:
            continue
        if price and d["price"] != price:
            continue
        out.append(n)
    return out


def cities_with_both(g, cat_a, price_a, cat_b):
    """MULTI-HOP: cities that have a `price_a` `cat_a` place AND a `cat_b` place.
    This is the query vector search cannot express — it joins two relationship
    paths that meet at the same City node.
    Cypher:
      MATCH (c:City)<-[:LOCATED_IN]-(p1:Place)-[:OF_CATEGORY]->(:Category {name:$cat_a})
      WHERE p1.price = $price_a
      MATCH (c)<-[:LOCATED_IN]-(p2:Place)-[:OF_CATEGORY]->(:Category {name:$cat_b})
      RETURN DISTINCT c.name
    """
    result = []
    for city, d in g.nodes(data=True):
        if d.get("type") != "city":
            continue
        # places located in this city = graph predecessors via LOCATED_IN
        local = [n for n in g.predecessors(city)
                 if g.nodes[n].get("type") == "place"]
        has_a = any(g.nodes[p]["category"] == cat_a and g.nodes[p]["price"] == price_a for p in local)
        has_b = any(g.nodes[p]["category"] == cat_b for p in local)
        if has_a and has_b:
            result.append(city)
    return result


def fact_exists(g, place_name, city):
    """VALIDATION: does this Place->City relationship actually exist in the graph?
    Cypher: MATCH (p:Place {name:$p})-[:LOCATED_IN]->(c:City {name:$city}) RETURN count(*)>0
    Use this to check an LLM's claim against ground truth."""
    return g.has_edge(place_name, city) and g.edges[place_name, city].get("rel") == "LOCATED_IN"


if __name__ == "__main__":
    g = build_graph()
    print(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    cities = [n for n, d in g.nodes(data=True) if d["type"] == "city"]
    print("cities:", cities)
    print("\n[single-hop] cheap food in Rome:", places(g, "Rome", "food", "cheap")[:4])
    print("\n[MULTI-HOP] cities with BOTH cheap food AND art:",
          cities_with_both(g, "food", "cheap", "art"))
    print("\n[validation] is 'Museums (Berlin)' located in Berlin?",
          fact_exists(g, "Museums (Berlin)", "Berlin"))
    print("[validation] is 'Museums (Berlin)' located in Paris?",
          fact_exists(g, "Museums (Berlin)", "Paris"))
