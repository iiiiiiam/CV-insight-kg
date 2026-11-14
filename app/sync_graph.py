"""Sync a small, repeatable MySQL paper slice to Neo4j for the first workflow demo."""

from __future__ import annotations

import argparse
import json
import os
import time

import requests
from sqlalchemy import select

from .db import SessionLocal
from .models import Paper

GRAPH_URL = os.getenv("NEO4J_HTTP_URL", "http://127.0.0.1:7474/db/neo4j/tx/commit")


def cypher(statement: str, parameters: dict | None = None) -> list[dict]:
    password = os.environ["NEO4J_PASSWORD"]
    for attempt in range(30):
        try:
            response = requests.post(
                GRAPH_URL,
                json={"statements": [{"statement": statement, "parameters": parameters or {}}]},
                auth=("neo4j", password),
                timeout=30,
            )
            if response.status_code == 503 and attempt < 29:
                time.sleep(2)
                continue
            break
        except requests.ConnectionError:
            if attempt == 29:
                raise
            time.sleep(2)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["results"][0]["data"]


def sync(venue: str, year: int, limit: int = 20) -> dict:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with SessionLocal() as db:
        papers = db.scalars(
            select(Paper).where(Paper.venue == venue, Paper.year == year, Paper.abstract.is_not(None))
            .order_by(Paper.id).limit(limit)
        ).all()
    if not papers:
        raise ValueError(f"No papers with abstracts found for {venue} {year}")
    rows = [{"id": p.id, "canonical_key": p.canonical_key, "title": p.title,
             "venue": p.venue, "year": p.year, "doi": p.doi,
             "abstract": p.abstract, "source_url": p.source_url} for p in papers]
    cypher("CREATE CONSTRAINT paper_mysql_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.mysql_id IS UNIQUE")
    cypher("CREATE CONSTRAINT venue_name IF NOT EXISTS FOR (v:Venue) REQUIRE v.name IS UNIQUE")
    cypher("""UNWIND $rows AS row
        MERGE (p:Paper {mysql_id: row.id})
        SET p.canonical_key = row.canonical_key, p.title = row.title,
            p.year = row.year, p.venue = row.venue, p.doi = row.doi,
            p.abstract = row.abstract, p.source_url = row.source_url
        MERGE (v:Venue {name: row.venue})
        MERGE (p)-[:PUBLISHED_IN]->(v)""", {"rows": rows})
    result = cypher("""MATCH (p:Paper)-[:PUBLISHED_IN]->(v:Venue {name: $venue})
        WHERE p.mysql_id IN $ids
        RETURN count(DISTINCT p) AS papers, count(DISTINCT v) AS venues""",
        {"venue": venue, "ids": [p.id for p in papers]})
    values = result[0]["row"]
    if values != [len(papers), 1]:
        raise RuntimeError(f"Graph verification failed: {values}")
    return {"venue": venue, "year": year, "sample_papers": len(papers),
            "graph_papers_verified": values[0], "graph_venues_verified": values[1],
            "example_mysql_id": papers[0].id, "example_title": papers[0].title}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", choices=("CVPR", "ICCV", "ECCV"))
    parser.add_argument("year", type=int)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(sync(args.venue, args.year, args.limit), ensure_ascii=False))
