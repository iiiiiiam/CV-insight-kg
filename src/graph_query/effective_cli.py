"""Explicit file import; publication requires a separate opt-in flag and CAS."""
import argparse
import json
import os
from .effective_source import FileEffectiveSource
from .repository import GraphRepository


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("--expected-revision")
    p.add_argument("--publish", action="store_true")
    p.add_argument("--expected-active")
    args = p.parse_args()
    document = FileEffectiveSource(args.file).load(args.expected_revision)
    repo = GraphRepository(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.getenv("NEO4J_USER", "neo4j"),
        os.environ["NEO4J_PASSWORD"],
        os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    try:
        repo.initialize()
        result = repo.ingest_effective(document)
        if args.publish:
            result["publication"] = repo.publish(result["id"], args.expected_active)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
