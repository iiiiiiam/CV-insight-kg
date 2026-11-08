"""Export exactly the configured public B knowledge without Neo4j or a running server."""

import argparse
import os
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

from server.application.knowledge_reading import reading_workspace
from src.knowledge_builder.effective_export import write_effective_export

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge_builder/exports/effective.json")
    parser.add_argument("--corpus")
    parser.add_argument("--reviews-dir")
    parser.add_argument("--vocabulary")
    parser.add_argument("--expected-revision")
    args = parser.parse_args()
    load_dotenv(ROOT / "server/.env", override=False)
    workbench = os.getenv("KNOWLEDGE_WORKBENCH_DATA")
    settings = SimpleNamespace(b_source_corpus=args.corpus or os.getenv("B_SOURCE_CORPUS") or None,
        b_reviews_directory=args.reviews_dir or os.getenv("B_REVIEWS_DIR") or (str(Path(workbench) / "reviews") if workbench else None),
        b_vocabulary_path=args.vocabulary or os.getenv("B_VOCABULARY_PATH") or None)
    document = reading_workspace(settings).export_effective(args.expected_revision)
    write_effective_export(document, args.output)
    print(f"Exported {document['counts']['papers']} papers to {args.output}; revision={document['revision']}", flush=True)


if __name__ == "__main__":
    main()
