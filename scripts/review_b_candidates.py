"""交互式人工审核入口。只接受实际输入，不预置自动确认决定。"""

import argparse
from pathlib import Path

from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import Entity
from src.knowledge_builder.review import ReviewSession


def main():
    parser = argparse.ArgumentParser(description="Review B candidates in memory")
    parser.add_argument(
        "--paper-index", type=int, default=1, help="Paper number, starting at 1"
    )
    parser.add_argument("--reviewer", required=True, help="Your reviewer name")
    args = parser.parse_args()
    if not args.reviewer.strip():
        parser.error("Reviewer name cannot be blank")
    root = Path(__file__).resolve().parents[1]
    papers = load_openalex_sample(root / "examples/week1_baseline.json")
    if not 1 <= args.paper_index <= len(papers):
        parser.error(f"Paper number must be between 1 and {len(papers)}")
    paper = papers[args.paper_index - 1]
    result = extract_candidates(paper)
    session = ReviewSession(paper, result)
    ids = [c.candidate_id for c in [*result.entities, *result.relations]]
    entity_numbers = {
        c.entity.key: index + 1 for index, c in enumerate(result.entities)
    }

    def summary():
        for status in ("pending", "confirmed", "rejected"):
            selection = session.select(status)
            print(
                f"{status}: entities={len(selection.entities)}, relations={len(selection.relations)}"
            )

    def display(number, detailed=False):
        item = session.get(ids[number - 1])
        content = item.content
        if isinstance(content, Entity):
            label = f"{content.kind}: {content.name}"
        else:
            label = f"#{entity_numbers[content.source]} --{content.kind}--> #{entity_numbers[content.target]}"
        print(f"{number}. [{item.status}] {label}")
        if detailed:
            for proof in item.evidence:
                location = (
                    f"{proof.field}[{proof.start}:{proof.end}]"
                    if proof.field != "metadata"
                    else str(proof.path)
                )
                print(f"   {location} = {proof.quote}")

    print("Paper:", paper.title)
    print("Paper ID:", paper.openalex_id)
    print("In-memory review only. Decisions are lost after quitting.")
    print(
        "Commands: list | show N | confirm N | reject N | name N | reopen N | summary | history | quit"
    )
    print(
        "Use show N to inspect evidence. Relations require both endpoints confirmed first."
    )
    if result.diagnostics:
        print("Input diagnostics:", result.diagnostics)
    summary()
    while True:
        try:
            parts = input("review> ").strip().split()
            if not parts:
                continue
            command = parts[0]
            if command == "quit":
                break
            if command == "summary":
                summary()
                continue
            if command == "list":
                for number in range(1, len(ids) + 1):
                    display(number)
                continue
            if command == "history":
                for event in session.history:
                    number = ids.index(event.after.candidate_id) + 1
                    print(
                        f"{event.sequence}. {event.action} #{number}: "
                        f"{event.before.status} -> {event.after.status}; "
                        f"{event.reviewer}; {event.reason}; {event.occurred_at}"
                    )
                    if event.before.content != event.after.content:
                        print("   before:", event.before.content)
                        print("   after: ", event.after.content)
                continue
            if (
                command not in {"show", "confirm", "reject", "name", "reopen"}
                or len(parts) != 2
            ):
                raise ValueError(
                    "Use list, show N, confirm N, reject N, name N, reopen N, summary, history or quit"
                )
            number = int(parts[1])
            if not 1 <= number <= len(ids):
                raise ValueError(f"Candidate number must be between 1 and {len(ids)}")
            display(number, detailed=True)
            if command == "show":
                continue
            name = input("New display name: ") if command == "name" else None
            reason = input("Reason (required): ")
            kwargs = {"reviewer": args.reviewer, "reason": reason}
            if command == "name":
                session.correct(ids[number - 1], name=name, **kwargs)
            else:
                getattr(session, command)(ids[number - 1], **kwargs)
            print("Recorded.")
            summary()
        except (EOFError, KeyboardInterrupt):
            break
        except ValueError as exc:
            print("Not recorded:", exc)
    print("Review ended. No files or databases were written.")


if __name__ == "__main__":
    main()
