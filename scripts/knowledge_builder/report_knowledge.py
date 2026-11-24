"""Build B's report attachment from an existing effective JSON, entirely offline."""

import argparse
import json
from pathlib import Path

from src.knowledge_builder.report_knowledge import build_report_knowledge, write_report_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effective", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-revision", help="Required effective knowledge revision, if already pinned")
    args = parser.parse_args()
    try:
        if args.effective.resolve() == args.output.resolve():
            raise ValueError("Report output must not overwrite the input effective file")
        document = json.loads(args.effective.read_text(encoding="utf-8"))
        report = build_report_knowledge(document, expected_revision=args.expected_revision)
        write_report_knowledge(report, args.output)
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(dict(output=str(args.output), revision=report["revision"], scope=report["scope"]),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
