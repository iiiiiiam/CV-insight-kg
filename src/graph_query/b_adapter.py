"""Explicit adapter for B's draft export. Never auto-confirms candidates.

Call B's load_exports/validate_exports first when their module is installed.
This boundary additionally checks status, source fingerprints and text slices.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .models import BatchInput


def adapt_confirmed(data, batch_id, source_batch_id):
    if (
        data.get("format_version") != "b-knowledge-export/0.1-draft"
        or data.get("status") != "confirmed"
        or data.get("kind") != "confirmed_knowledge"
    ):
        raise ValueError("only the supported confirmed B export is accepted")
    if not data.get("papers"):
        raise ValueError(
            "B has no confirmed knowledge; do not fabricate human decisions"
        )
    entities = {}
    relations = {}
    schemas = set()
    vocabularies = set()
    for part in data["papers"]:
        if part["endpoint_context"]:
            raise ValueError("confirmed export must not have endpoint_context")
        raw = part["input"]
        origin = part["origin"]
        digest = hashlib.sha256(
            json.dumps(
                raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if digest != origin["input_fingerprint"]:
            raise ValueError("B input fingerprint mismatch")
        schemas.add(origin["source_schema_version"])
        vocabularies.add(origin["vocabulary_version"])
        paper_nodes = [
            x["item"]["content"]["key"]
            for x in part["entities"]
            if x["item"]["content"].get("kind") == "paper"
        ]
        if len(paper_nodes) != 1:
            raise ValueError("confirmed partition must contain one paper entity")
        pid = paper_nodes[0]
        for group in ("entities", "relations"):
            for entry in part[group]:
                item = entry["item"]
                review = entry["review"]
                if (
                    item["status"] != "confirmed"
                    or not review
                    or review["action"] != "confirm"
                ):
                    raise ValueError("item lacks an explicit confirm decision")
                if not review["reviewer"].strip() or not review["reason"].strip():
                    raise ValueError("review must identify reviewer and reason")
                content = item["content"]
                if group == "entities":
                    n = dict(
                        id=content["key"],
                        kind=content["kind"],
                        name=content["name"],
                        source_id=content["source_id"],
                        updated_at=review["occurred_at"],
                    )
                    if n["kind"] == "paper":
                        n.update(
                            year=raw["year"],
                            abstract=raw["abstract"],
                            source_url=raw["source_url"],
                            missing_fields=["institution_if_not_evidenced"],
                        )
                    previous = entities.get(n["id"])
                    if previous and (previous["kind"], previous["name"]) != (
                        n["kind"],
                        n["name"],
                    ):
                        raise ValueError(
                            "conflicting entity definitions across partitions"
                        )
                    entities[n["id"]] = n
                else:
                    evidence = []
                    for e in item["evidence"]:
                        if (
                            e["paper_id"] != raw["openalex_id"]
                            or e["input_fingerprint"] != digest
                            or e["source_url"] != raw["source_url"]
                        ):
                            raise ValueError("evidence provenance mismatch")
                        if e["field"] in ("title", "abstract"):
                            text = raw[e["field"]] or ""
                            if (
                                e["start"] is None
                                or e["end"] is None
                                or text[e["start"] : e["end"]] != e["quote"]
                            ):
                                raise ValueError(
                                    "B evidence offsets do not match original text"
                                )
                        elif e["field"] == "metadata":
                            value = raw
                            for key in e["path"]:
                                value = value[key]
                            # B metadata quote is canonical JSON, not str(value).
                            if (
                                json.dumps(
                                    value,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                                != e["quote"]
                            ):
                                raise ValueError(
                                    "B metadata evidence does not match source path"
                                )
                        evidence.append(
                            dict(
                                paper_id=pid,
                                source_url=e["source_url"],
                                field=e["field"],
                                quote=e["quote"],
                                locator=json.dumps(e["path"])
                                if e["field"] == "metadata"
                                else f"{e['start']}:{e['end']}",
                                reviewer=review["reviewer"],
                                reviewed_at=review["occurred_at"],
                            )
                        )
                    key = (content["source"], content["kind"], content["target"])
                    if key not in relations:
                        relations[key] = dict(
                            source=key[0],
                            kind=key[1],
                            target=key[2],
                            status="confirmed",
                            evidence=[],
                        )
                    relations[key]["evidence"].extend(evidence)
    if len(schemas) != 1 or len(vocabularies) != 1:
        raise ValueError("one batch requires one schema and vocabulary version")
    return BatchInput(
        contract_version="c-graph/1.0",
        batch_id=batch_id,
        source_batch_id=source_batch_id,
        schema_version=schemas.pop(),
        vocabulary_version=vocabularies.pop(),
        provenance="reviewed_export",
        entities=list(entities.values()),
        relations=list(relations.values()),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("confirmed_json")
    p.add_argument("output")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--source-batch-id", required=True)
    a = p.parse_args()
    result = adapt_confirmed(
        json.loads(Path(a.confirmed_json).read_text(encoding="utf-8")),
        a.batch_id,
        a.source_batch_id,
    )
    with Path(a.output).open("x", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))
