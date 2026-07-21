"""
Week 3 - Day 3 (Course Day 13) - REAL knowledge graph in Neo4j (graph database).

This replaces the NetworkX simulation with an actual graph DB queried in Cypher.
Run a local Neo4j first (we used Docker):
    docker run -d --name neo4j-kg -p 7687:7687 -p 7474:7474 \
        -e NEO4J_AUTH=neo4j/testpassword123 neo4j:5

Graph model (property graph):
    (:Place {name, price}) -[:LOCATED_IN]->  (:City {name})
    (:Place {name, price}) -[:OF_CATEGORY]-> (:Category {name})

Cypher is the point: the SAME multi-hop question that vector search can't express
is one MATCH in Cypher. This is grounding + reasoning + validation on real infra.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "week-2" / "day-5"))
import store as t_store

load_dotenv()
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "testpassword123"))

_driver = GraphDatabase.driver(URI, auth=AUTH)


def load_from_store():
    """Pull places from the Day-5 Qdrant store and MERGE them into Neo4j as a graph."""
    client = t_store.load()
    points, _ = client.scroll(collection_name="travel", limit=10000, with_payload=True)
    rows, seen = [], set()
    for p in points:
        pl = p.payload
        name = f"{pl['title']} ({pl['city']})"
        if name in seen:
            continue
        seen.add(name)
        rows.append({"name": name, "price": pl["price_level"],
                     "city": pl["city"], "cat": pl["category"]})

    with _driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")                       # clean slate
        # constraints double as VALIDATION: a City/Category name is unique
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:City) REQUIRE c.name IS UNIQUE")
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (k:Category) REQUIRE k.name IS UNIQUE")
        # one parameterized Cypher builds the whole graph (MERGE = upsert, no dupes)
        s.run("""
            UNWIND $rows AS row
            MERGE (c:City {name: row.city})
            MERGE (k:Category {name: row.cat})
            MERGE (p:Place {name: row.name})
              SET p.price = row.price
            MERGE (p)-[:LOCATED_IN]->(c)
            MERGE (p)-[:OF_CATEGORY]->(k)
        """, rows=rows)
        counts = s.run("MATCH (n) RETURN count(n) AS nodes").single()["nodes"]
        rels = s.run("MATCH ()-[r]->() RETURN count(r) AS rels").single()["rels"]
    return counts, rels


def places(city=None, category=None, price=None):
    """Single-hop filter (real Cypher)."""
    q = """
        MATCH (p:Place)-[:LOCATED_IN]->(c:City), (p)-[:OF_CATEGORY]->(k:Category)
        WHERE ($city IS NULL OR c.name=$city)
          AND ($category IS NULL OR k.name=$category)
          AND ($price IS NULL OR p.price=$price)
        RETURN p.name AS name LIMIT 10
    """
    with _driver.session() as s:
        return [r["name"] for r in s.run(q, city=city, category=category, price=price)]


def cities_with_both(cat_a, price_a, cat_b):
    """MULTI-HOP join — the query vector search cannot express."""
    q = """
        MATCH (c:City)<-[:LOCATED_IN]-(p1:Place)-[:OF_CATEGORY]->(:Category {name:$cat_a})
        WHERE p1.price = $price_a
        MATCH (c)<-[:LOCATED_IN]-(:Place)-[:OF_CATEGORY]->(:Category {name:$cat_b})
        RETURN DISTINCT c.name AS city
    """
    with _driver.session() as s:
        return [r["city"] for r in s.run(q, cat_a=cat_a, price_a=price_a, cat_b=cat_b)]


def fact_exists(place_name, city):
    """VALIDATION: does this exact relationship exist? (deterministic)"""
    q = "MATCH (p:Place {name:$p})-[:LOCATED_IN]->(c:City {name:$city}) RETURN count(*) > 0 AS ok"
    with _driver.session() as s:
        return s.run(q, p=place_name, city=city).single()["ok"]


def close():
    _driver.close()


if __name__ == "__main__":
    n, r = load_from_store()
    print(f"Loaded into Neo4j: {n} nodes, {r} relationships")
    print("\n[single-hop] cheap food in Rome:", places("Rome", "food", "cheap")[:4])
    print("[MULTI-HOP] cities with BOTH cheap food AND art:", cities_with_both("food", "cheap", "art"))
    print("[validation] 'Museums (Berlin)' in Berlin?", fact_exists("Museums (Berlin)", "Berlin"))
    print("[validation] 'Museums (Berlin)' in Paris? ", fact_exists("Museums (Berlin)", "Paris"))
    close()
