"""Complete effective knowledge snapshots for graph handoff, separate from confirmed.json."""

import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .extraction import RELATIONS, fingerprint, validate_evidence
from .feedback import FeedbackConflict
from .models import Evidence, PaperInput

FORMAT = "knowledge-effective/1.0"
REVIEW_STATES = {"automatic", "human_confirmed", "human_corrected"}


def _rule_fingerprint(workspace):
    names = ["extraction.py", "feedback.py", "effective_export.py"]
    if workspace.source_records is not None:
        names += ["source_enrichment.py", "research_directions.py", "text_signals.py", "curated_vocabulary.py", "vocabulary_cv.json"]
    root = Path(__file__).parent
    return fingerprint({name: (root / name).read_text(encoding="utf-8") for name in names})


def _content(document):
    return {k: v for k, v in document.items() if k not in {"revision", "generated_at"}}


def build_effective_export(workspace, *, expected_revision=None):
    """Read feedback once and use the exact public projection for every partition."""
    data = workspace.store.read()
    rules = _rule_fingerprint(workspace)
    parts, counts = [], Counter()
    for identifier in sorted(workspace.papers):
        public, _, _, result, provenance = workspace._material(identifier, data, with_provenance=True)
        part = dict(input=asdict(workspace.papers[identifier]), origin=dict(
            input_fingerprint=result.input_fingerprint, public_revision=public["revision"],
            schema_version=result.schema_version, extraction_rule_version=result.rule_version,
            vocabulary_version=result.vocabulary_version, vocabulary_fingerprint=result.vocabulary_fingerprint),
            entities=[], relations=[], source_classifications=public.get("source_enrichment", {}).get("source_classifications", []))
        for group in ("entities", "relations"):
            for item in sorted(public[group], key=lambda i: i["candidate_id"]):
                part[group].append({**item, "provenance": provenance[item["candidate_id"]]})
                counts[group] += 1
                counts[provenance[item["candidate_id"]]["review_state"]] += 1
        parts.append(part)
    if workspace.store.read()["revision"] != data["revision"] or rules != _rule_fingerprint(workspace):
        raise FeedbackConflict("导出期间知识或规则已变化，请重新导出")
    content = dict(format_version=FORMAT, kind="effective_knowledge", mode="full_snapshot",
        publication_policy="automatic_results_and_effective_public_corrections",
        rule_fingerprint=rules, base_vocabulary_fingerprint=fingerprint(workspace.vocabulary),
        counts=dict(papers=len(parts), entities=counts["entities"], relations=counts["relations"],
                    review_states={state: counts[state] for state in sorted(REVIEW_STATES)}), papers=parts)
    revision = fingerprint(content)
    if expected_revision is not None and expected_revision != revision:
        raise FeedbackConflict("当前有效知识版本已变化，请刷新后重新导出")
    document = json.loads(json.dumps({**content, "revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
    validate_effective_export(document)
    return document


def validate_effective_export(document):
    """Validate integrity, source evidence, types and per-paper graph endpoints."""
    if (document.get("format_version") != FORMAT or document.get("kind") != "effective_knowledge"
        or document.get("mode") != "full_snapshot" or document.get("revision") != fingerprint(_content(document))):
        raise ValueError("Invalid effective knowledge version or checksum")
    seen, counts = set(), Counter()
    for part in document["papers"]:
        paper = PaperInput(**part["input"])
        if paper.openalex_id in seen or part["origin"]["input_fingerprint"] != fingerprint(asdict(paper)):
            raise ValueError("Duplicate paper or changed effective input")
        seen.add(paper.openalex_id)
        entities, identifiers = {}, set()
        for group in ("entities", "relations"):
            for item in part[group]:
                if item["candidate_id"] in identifiers:
                    raise ValueError("Duplicate effective candidate")
                identifiers.add(item["candidate_id"])
                info = item["provenance"]
                if (info["generation"] != "automatic" or info["review_state"] not in REVIEW_STATES
                    or type(info["rule_adjusted"]) is not bool):
                    raise ValueError("Invalid effective provenance")
                if not item["evidence"]:
                    raise ValueError("Effective items require source evidence")
                for raw in item["evidence"]:
                    validate_evidence(paper, Evidence(**{**raw, "path": tuple(raw["path"])}))
                c = item["content"]
                if group == "entities":
                    if c["key"] in entities or c["kind"] not in {"paper", "author", "institution", "venue", "topic", "method", "task", "dataset"}:
                        raise ValueError("Duplicate entity key or unsupported type")
                    entities[c["key"]] = c
                else:
                    types = RELATIONS.get(c["kind"])
                    if (not types or c["source"] not in entities or c["target"] not in entities
                        or (entities[c["source"]]["kind"], entities[c["target"]]["kind"]) != types):
                        raise ValueError("Dangling or mistyped effective relation")
                counts[group] += 1
                counts[info["review_state"]] += 1
    expected = dict(papers=len(seen), entities=counts["entities"], relations=counts["relations"],
                    review_states={state: counts[state] for state in sorted(REVIEW_STATES)})
    if document["counts"] != expected:
        raise ValueError("Effective export counts mismatch")
    return document


def write_effective_export(document, path):
    validate_effective_export(document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(document, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
