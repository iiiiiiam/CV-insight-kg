"""Offline B batch operations. No server, Neo4j or fixed-corpus modification."""

import argparse
import hashlib
import json
from pathlib import Path

from src.knowledge_builder.batches import BatchRegistry, BatchConflict
from src.knowledge_builder.effective_export import write_effective_export
from src.knowledge_builder.batch_sources import BatchSources
from src.knowledge_builder.models import PaperInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("data/knowledge_builder/batches/ledger.json"))
    parser.add_argument("--source-corpus", type=Path, help="Reuse the existing validated source corpus")
    parser.add_argument("--offline", action="store_true", help="Use source caches without HTTP")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("file", type=Path)
    withdraw = commands.add_parser("withdraw")
    withdraw.add_argument("batch_code")
    commands.add_parser("snapshot")
    commands.add_parser("status")
    commands.add_parser("enrich")
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path)
    export.add_argument("--feedback", type=Path)
    args = parser.parse_args()
    registry = BatchRegistry(args.registry)
    source_store = BatchSources(args.registry, corpus_path=args.source_corpus, offline=args.offline)
    try:
        if args.command == "ingest":
            body = args.file.read_bytes()
            checksum = args.file.with_suffix(args.file.suffix + ".sha256")
            if checksum.exists():
                expected = checksum.read_text(encoding="utf-8").split()[0]
                if hashlib.sha256(body).hexdigest() != expected:
                    raise ValueError("Handoff file checksum mismatch; ledger unchanged")
            result = registry.ingest(json.loads(body.decode("utf-8")))
        elif args.command == "withdraw":
            result = registry.withdraw(args.batch_code)
        elif args.command == "snapshot":
            result = registry.snapshot()
        elif args.command == "enrich":
            papers = [PaperInput(**p["input"]) for p in registry.snapshot()["papers"]]
            result = source_store.prepare(papers)
        elif args.command == "status":
            state = registry.read()
            result = dict(ledger_revision=state["revision"], snapshot_revision=registry.snapshot()["revision"],
                batches=[dict(batch_code=b["batch_code"], active=b["active"], papers=len(b["papers"])) for b in state["batches"]],
                failed_attempts=sum(e["action"] == "ingest_failed" for e in state["events"]))
        else:
            output = args.output or args.registry.parent / "effective.json"
            feedback = args.feedback or args.registry.parent / "feedback" / "state.json"
            workspace = registry.workspace(feedback, source_store=source_store)
            document = workspace.export_effective()
            if registry.snapshot()["revision"] != workspace.batch_snapshot_revision:
                raise BatchConflict("Batch inputs changed during export; retry")
            write_effective_export(document, output)
            result = dict(output=str(output), revision=document["revision"],
                          input_snapshot_revision=workspace.batch_snapshot_revision, counts=document["counts"])
    except (ValueError, LookupError, OSError, IndexError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
