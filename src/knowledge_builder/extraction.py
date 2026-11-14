"""元数据关联和词表提及抽取；结果初始待审，支持按需人工校验。"""

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from .models import (
    Entity,
    EntityCandidate,
    Evidence,
    ExtractionResult,
    PaperInput,
    RelationCandidate,
)

SCHEMA_VERSION = "b-knowledge/0.1-draft"
RULE_VERSION = "metadata-and-mentions/0.1"
RELATIONS = {
    "has_author": ("paper", "author"),
    "affiliated_with": ("author", "institution"),
    "published_in": ("paper", "venue"),
    "mentions_topic": ("paper", "topic"),
    "mentions_method": ("paper", "method"),
    "mentions_task": ("paper", "task"),
    "mentions_dataset": ("paper", "dataset"),
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def candidate_id(paper_id, *parts):
    return fingerprint([SCHEMA_VERSION, paper_id, *parts])


def load_vocabulary(path: str | Path | None = None) -> dict:
    """也可加载调用方指定的词表；不依赖运行时当前目录。"""
    path = (
        Path(path) if path is not None else Path(__file__).with_name("vocabulary.json")
    )
    vocabulary = json.loads(path.read_text(encoding="utf-8"))
    validate_vocabulary(vocabulary)
    return vocabulary


def validate_vocabulary(vocabulary):
    if not isinstance(vocabulary, dict) or not isinstance(
        vocabulary.get("version"), str
    ):
        raise ValueError("Vocabulary requires a version")
    if not vocabulary["version"].strip() or not isinstance(
        vocabulary.get("terms"), list
    ):
        raise ValueError("Invalid vocabulary")
    keys, aliases = set(), set()
    for term in vocabulary["terms"]:
        if not isinstance(term, dict) or term.get("kind") not in {
            "topic",
            "method",
            "task",
            "dataset",
        }:
            raise ValueError("Invalid vocabulary entity type")
        if any(
            not isinstance(term.get(k), str) or not term[k].strip()
            for k in ("key", "name")
        ):
            raise ValueError("Vocabulary requires key and name")
        key = (term["kind"], term["key"])
        if key in keys:
            raise ValueError("Duplicate vocabulary key")
        keys.add(key)
        if not isinstance(term.get("aliases"), list) or not term["aliases"]:
            raise ValueError("Vocabulary requires aliases")
        for alias in term["aliases"]:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("Invalid vocabulary alias")
            normalized = alias.casefold()
            if normalized in aliases:
                raise ValueError("Ambiguous or duplicate vocabulary alias")
            aliases.add(normalized)


def validate_evidence(paper: PaperInput, evidence: Evidence):
    data = asdict(paper)
    if (
        evidence.paper_id,
        evidence.dataset_id,
        evidence.source_url,
        evidence.input_fingerprint,
    ) != (paper.openalex_id, paper.dataset_id, paper.source_url, fingerprint(data)):
        raise ValueError("Evidence belongs to a different input")
    if evidence.field in ("title", "abstract"):
        value = data[evidence.field]
        if (
            not isinstance(value, str)
            or evidence.path
            or type(evidence.start) is not int
            or type(evidence.end) is not int
            or not 0 <= evidence.start < evidence.end <= len(value)
            or value[evidence.start : evidence.end] != evidence.quote
        ):
            raise ValueError("Invalid text evidence")
    elif evidence.field == "metadata":
        if not evidence.path or evidence.start is not None or evidence.end is not None:
            raise ValueError("Invalid metadata evidence")
        value = data
        try:
            for part in evidence.path:
                if isinstance(value, list):
                    if type(part) is not int or not 0 <= part < len(value):
                        raise ValueError("Invalid metadata index")
                elif not isinstance(value, dict) or not isinstance(part, str):
                    raise ValueError("Invalid metadata path")
                value = value[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Missing metadata path") from exc
        if canonical_json(value) != evidence.quote:
            raise ValueError("Metadata value differs from evidence")
    else:
        raise ValueError("Unknown evidence field")


def extract_candidates(
    paper: PaperInput, vocabulary: dict | None = None
) -> ExtractionResult:
    """不修改 paper；不把词条命中推断为使用、提出或评测。"""
    vocabulary = load_vocabulary() if vocabulary is None else vocabulary
    validate_vocabulary(vocabulary)
    data = asdict(paper)
    digest = fingerprint(data)
    entities, relations, diagnostics = {}, {}, []

    def evidence(field, quote, start=None, end=None, path=()):
        return Evidence(
            paper.openalex_id,
            paper.dataset_id,
            paper.source_url,
            digest,
            field,
            quote,
            start,
            end,
            path,
        )

    def metadata(path):
        value = data
        for part in path:
            value = value[part]
        return evidence("metadata", canonical_json(value), path=path)

    def add_entity(entity, proofs):
        if entity.key not in entities:
            entities[entity.key] = EntityCandidate(
                candidate_id(paper.openalex_id, "entity", entity.key), entity, []
            )
        elif entities[entity.key].entity.name != entity.name:
            diagnostics.append(f"Conflicting names for {entity.key}; kept first label")
        for proof in proofs:
            if proof not in entities[entity.key].evidence:
                entities[entity.key].evidence.append(proof)
        return entity.key

    def add_relation(source, kind, target, proofs):
        key = (source, kind, target)
        if key not in relations:
            relations[key] = RelationCandidate(
                candidate_id(paper.openalex_id, "relation", *key),
                source,
                kind,
                target,
                [],
            )
        for proof in proofs:
            if proof not in relations[key].evidence:
                relations[key].evidence.append(proof)

    root = add_entity(
        Entity("paper:" + paper.openalex_id, "paper", paper.title, paper.openalex_id),
        [metadata(("openalex_id",)), metadata(("title",))],
    )
    if paper.venue.strip():
        # 本地名称键；保留原样，不冒充来源 ID 或合并不同会议别名。
        venue = add_entity(
            Entity("venue:local:" + paper.venue, "venue", paper.venue),
            [metadata(("venue",))],
        )
        add_relation(root, "published_in", venue, [metadata(("venue",))])
    else:
        diagnostics.append("Missing venue")

    def source_entity(record, kind, path):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("display_name"), str)
            or not record["display_name"].strip()
        ):
            diagnostics.append(f"Missing {kind} name at {path}")
            return None, []
        source_id = record.get("id")
        proofs = [metadata((*path, "display_name"))]
        if isinstance(source_id, str) and source_id.strip():
            key = kind + ":" + source_id
            proofs.append(metadata((*path, "id")))
        else:
            source_id = None
            key = kind + ":unresolved:" + fingerprint([paper.openalex_id, path])
            diagnostics.append(f"Unresolved {kind} ID at {path}")
        return add_entity(
            Entity(key, kind, record["display_name"], source_id), proofs
        ), proofs

    if not paper.authorships:
        diagnostics.append("Missing authorships")
    for i, authorship in enumerate(paper.authorships):
        author, author_proofs = source_entity(
            authorship.get("author"), "author", ("authorships", i, "author")
        )
        if author is None:
            continue
        add_relation(root, "has_author", author, author_proofs)
        institutions = authorship.get("institutions")
        if not isinstance(institutions, list) or not institutions:
            diagnostics.append(f"Missing institutions at authorships[{i}]")
            continue
        for j, record in enumerate(institutions):
            institution, proofs = source_entity(
                record, "institution", ("authorships", i, "institutions", j)
            )
            if institution is not None:
                add_relation(
                    author, "affiliated_with", institution, author_proofs + proofs
                )

    # 在原文上匹配，忽略大小写。连字符视为词内字符，避免 RT-DETR 中再命中 DETR。
    # 同一位置的别名重叠时优先最长匹配；不会把 YOLO-World 自动归并为 YOLO。
    aliases = sorted(
        ((alias, term) for term in vocabulary["terms"] for alias in term["aliases"]),
        key=lambda item: (-len(item[0]), item[0]),
    )
    for field in ("title", "abstract"):
        text = getattr(paper, field)
        if text is None:
            diagnostics.append("Missing abstract")
            continue
        occupied = []
        for alias, term in aliases:
            pattern = r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])"
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.span()
                if any(start < b and end > a for a, b in occupied):
                    continue
                occupied.append((start, end))
                proof = evidence(field, text[start:end], start, end)
                target = add_entity(
                    Entity(
                        term["kind"] + ":term:" + term["key"],
                        term["kind"],
                        term["name"],
                    ),
                    [proof],
                )
                add_relation(root, "mentions_" + term["kind"], target, [proof])

    result = ExtractionResult(
        paper.openalex_id,
        digest,
        SCHEMA_VERSION,
        RULE_VERSION,
        vocabulary["version"],
        fingerprint(vocabulary),
        list(entities.values()),
        list(relations.values()),
        diagnostics,
    )
    validate_result(paper, result)
    return result


def validate_result(paper: PaperInput, result: ExtractionResult):
    """检查待审核结果的结构、方向与证据；不判断学术内容是否正确。"""
    if result.paper_id != paper.openalex_id or result.input_fingerprint != fingerprint(
        asdict(paper)
    ):
        raise ValueError("Result belongs to a different input")
    entities = {candidate.entity.key: candidate for candidate in result.entities}
    if len(entities) != len(result.entities):
        raise ValueError("Duplicate entity key")
    ids = set()
    for candidate in [*result.entities, *result.relations]:
        if (
            candidate.status != "pending"
            or not candidate.evidence
            or candidate.candidate_id in ids
        ):
            raise ValueError("Invalid candidate status, evidence or duplicate ID")
        ids.add(candidate.candidate_id)
        for proof in candidate.evidence:
            validate_evidence(paper, proof)
    kinds = {kind for pair in RELATIONS.values() for kind in pair}
    for candidate in result.entities:
        entity = candidate.entity
        if entity.kind not in kinds or not entity.name.strip() or not entity.key:
            raise ValueError("Invalid entity")
        if candidate.candidate_id != candidate_id(
            paper.openalex_id, "entity", entity.key
        ):
            raise ValueError("Invalid entity candidate ID")
    triples = set()
    for relation in result.relations:
        if relation.source not in entities or relation.target not in entities:
            raise ValueError("Missing relation endpoint")
        pair = (
            entities[relation.source].entity.kind,
            entities[relation.target].entity.kind,
        )
        if RELATIONS.get(relation.kind) != pair:
            raise ValueError("Invalid relation direction or types")
        target_proofs = entities[relation.target].evidence
        if any(
            proof not in target_proofs
            for proof in relation.evidence
            if relation.kind != "affiliated_with"
        ):
            raise ValueError("Relation evidence does not support its target")
        if relation.kind == "affiliated_with":
            author_proofs = entities[relation.source].evidence
            allowed = author_proofs + target_proofs
            if any(proof not in allowed for proof in relation.evidence):
                raise ValueError("Affiliation evidence does not support endpoints")
            author_rows = {
                e.path[:2]
                for e in relation.evidence
                if len(e.path) == 4
                and e.path[0] == "authorships"
                and e.path[2] == "author"
                and e in author_proofs
            }
            institution_rows = {
                e.path[:2]
                for e in relation.evidence
                if len(e.path) == 5
                and e.path[0] == "authorships"
                and e.path[2] == "institutions"
                and e in target_proofs
            }
            if not author_rows or author_rows != institution_rows:
                raise ValueError("Affiliation must use the same authorship")
        triple = (relation.source, relation.kind, relation.target)
        if triple in triples or relation.candidate_id != candidate_id(
            paper.openalex_id, "relation", *triple
        ):
            raise ValueError("Duplicate relation or invalid candidate ID")
        triples.add(triple)
