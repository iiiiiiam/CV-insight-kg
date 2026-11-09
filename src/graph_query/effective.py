"""Independent knowledge-effective/1.0 validation and projection; no invented reviews."""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from .models import RELATIONS


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def revision(document):
    return fingerprint(
        {k: v for k, v in document.items() if k not in ("revision", "generated_at")}
    )


def validate_effective(document):
    if (
        document.get("format_version") != "knowledge-effective/1.0"
        or document.get("kind") != "effective_knowledge"
        or document.get("mode") != "full_snapshot"
        or document.get("publication_policy")
        != "automatic_results_and_effective_public_corrections"
        or not re.fullmatch("[a-f0-9]{64}", document.get("revision", ""))
        or revision(document) != document["revision"]
    ):
        raise ValueError("Invalid effective format, policy or revision")
    if set(document) != {
        "format_version",
        "kind",
        "mode",
        "publication_policy",
        "revision",
        "generated_at",
        "rule_fingerprint",
        "base_vocabulary_fingerprint",
        "counts",
        "papers",
    }:
        raise ValueError("Unknown effective root fields")
    stamp = datetime.fromisoformat(document["generated_at"])
    if stamp.utcoffset() is None:
        raise ValueError("generated_at must include timezone")
    for field in ("rule_fingerprint", "base_vocabulary_fingerprint"):
        if not re.fullmatch("[a-f0-9]{64}", document[field]):
            raise ValueError("Invalid version fingerprint")
    if any(
        type(document["counts"][k]) is not int
        for k in ("papers", "entities", "relations")
    ) or any(type(v) is not int for v in document["counts"]["review_states"].values()):
        raise ValueError("Counts must be integers")
    papers = set()
    counts = Counter()
    for part in document["papers"]:
        if set(part) != {
            "input",
            "origin",
            "entities",
            "relations",
            "source_classifications",
        }:
            raise ValueError("Unknown partition fields")
        raw = part["input"]
        origin = part["origin"]
        pid = raw["openalex_id"]
        if pid in papers or fingerprint(raw) != origin["input_fingerprint"]:
            raise ValueError("Duplicate or changed paper")
        papers.add(pid)
        if not isinstance(raw["year"], int) or not 1900 <= raw["year"] <= 2100:
            raise ValueError("Invalid year")
        for field in ("public_revision", "vocabulary_fingerprint"):
            if not re.fullmatch("[a-f0-9]{64}", origin[field]):
                raise ValueError("Invalid origin revision")
        for field in (
            "schema_version",
            "extraction_rule_version",
            "vocabulary_version",
        ):
            if not origin[field]:
                raise ValueError("Missing origin version")
        nodes = {}
        ids = set()
        links = set()
        for group in ("entities", "relations"):
            for item in part[group]:
                if set(item) != {"candidate_id", "content", "evidence", "provenance"}:
                    raise ValueError("Unknown item fields")
                cid = item["candidate_id"]
                info = item["provenance"]
                c = item["content"]
                if not isinstance(cid, str) or not cid or cid in ids:
                    raise ValueError("Duplicate candidate ID")
                ids.add(cid)
                if (
                    info["generation"] != "automatic"
                    or info["review_state"]
                    not in ("automatic", "human_confirmed", "human_corrected")
                    or type(info["rule_adjusted"]) is not bool
                ):
                    raise ValueError("Invalid provenance")
                if not item["evidence"]:
                    raise ValueError("Evidence required")
                for e in item["evidence"]:
                    if (
                        e["paper_id"],
                        e["dataset_id"],
                        e["source_url"],
                        e["input_fingerprint"],
                    ) != (
                        pid,
                        raw["dataset_id"],
                        raw["source_url"],
                        origin["input_fingerprint"],
                    ):
                        raise ValueError("Evidence source mismatch")
                    if e["field"] in ("title", "abstract"):
                        start, end = e["start"], e["end"]
                        text = raw[e["field"]] or ""
                        if (
                            type(start) is not int
                            or type(end) is not int
                            or not 0 <= start < end <= len(text)
                            or text[start:end] != e["quote"]
                            or e["path"]
                        ):
                            raise ValueError("Unicode evidence offset mismatch")
                    elif e["field"] == "metadata":
                        if (
                            e["start"] is not None
                            or e["end"] is not None
                            or not e["path"]
                        ):
                            raise ValueError("Invalid metadata locator")
                        value = raw
                        for key in e["path"]:
                            value = value[key]
                        if canonical(value) != e["quote"]:
                            raise ValueError("Metadata evidence mismatch")
                    else:
                        raise ValueError("Unknown evidence field")
                if group == "entities":
                    if (
                        c["key"] in nodes
                        or c["kind"]
                        not in {x for pair in RELATIONS.values() for x in pair}
                        or not c["name"]
                    ):
                        raise ValueError("Invalid entity")
                    nodes[c["key"]] = c
                else:
                    key = (c["source"], c["kind"], c["target"])
                    if (
                        key in links
                        or c["source"] not in nodes
                        or c["target"] not in nodes
                        or (nodes[c["source"]]["kind"], nodes[c["target"]]["kind"])
                        != RELATIONS.get(c["kind"])
                    ):
                        raise ValueError("Invalid relation endpoints")
                    links.add(key)
                counts[group] += 1
                counts[info["review_state"]] += 1
        if sum(c["kind"] == "paper" for c in nodes.values()) != 1:
            raise ValueError("Partition needs exactly one paper entity")
        for classification in part["source_classifications"]:
            if classification.get("basis") != "source_classification":
                raise ValueError("Invalid source classification basis")
    expected = dict(
        papers=len(papers),
        entities=counts["entities"],
        relations=counts["relations"],
        review_states={
            s: counts[s] for s in ("automatic", "human_confirmed", "human_corrected")
        },
    )
    if document["counts"] != expected:
        raise ValueError("Effective counts mismatch")
    return document


def project(document):
    validate_effective(document)
    nodes = {}
    edges = []
    for part in sorted(document["papers"], key=lambda x: x["input"]["openalex_id"]):
        if set(part) != {
            "input",
            "origin",
            "entities",
            "relations",
            "source_classifications",
        }:
            raise ValueError("Unknown partition fields")
        raw = part["input"]
        pid = next(
            i["content"]["key"]
            for i in part["entities"]
            if i["content"]["kind"] == "paper"
        )
        for item in part["entities"]:
            c = item["content"]
            key = c["key"]
            if key not in nodes:
                nodes[key] = dict(
                    id=key,
                    kind=c["kind"],
                    name=c["name"],
                    source_id=c["source_id"],
                    updated_at=document["generated_at"],
                    contexts=[],
                )
            if (nodes[key]["kind"], nodes[key]["source_id"]) != (
                c["kind"],
                c["source_id"],
            ):
                raise ValueError("Conflicting stable entity kind")
            nodes[key]["contexts"].append(
                dict(paper_id=pid, **item, origin=part["origin"])
            )
            if c["kind"] == "paper":
                nodes[key].update(
                    title=raw["title"],
                    abstract=raw["abstract"],
                    year=raw["year"],
                    source_url=raw["source_url"],
                    effective_partition_json=canonical(part),
                )
        for item in part["relations"]:
            c = item["content"]
            edges.append(
                dict(
                    id=fingerprint([pid, item["candidate_id"]]),
                    candidate_id=item["candidate_id"],
                    source=c["source"],
                    target=c["target"],
                    kind=c["kind"],
                    status="effective",
                    paper_ids=[pid],
                    paper_id=pid,
                    evidence_json=canonical(item["evidence"]),
                    **item["provenance"]
                )
            )
    for n in nodes.values():
        n["contexts_json"] = canonical(n.pop("contexts"))
    return list(nodes.values()), edges
