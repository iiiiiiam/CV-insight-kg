"""Administrative local CLI. Same validation and atomic transactions as the API."""
import argparse
import json
import os
from pathlib import Path

from .models import BatchInput
from .repository import GraphRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "import", "check", "publish"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--expected-active")
    parser.add_argument("--allow-developer-fixture", action="store_true")
    args = parser.parse_args()
    repo = GraphRepository(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.getenv("NEO4J_USER", "neo4j"),
        os.environ["NEO4J_PASSWORD"],
        os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    try:
        repo.initialize()
        if args.command == "import":
            result = repo.ingest(
                BatchInput.model_validate_json(
                    Path(args.value).read_text(encoding="utf-8")
                )
            )
        elif args.command == "check":
            result = repo.batch(args.value)
        elif args.command == "publish":
            result = repo.publish(
                args.value, args.expected_active, args.allow_developer_fixture
            )
        else:
            result = {"initialized": True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
