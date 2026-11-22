"""Explainable paper-knowledge tags, never claims about an author's expertise."""

from copy import deepcopy

from .effective_export import validate_effective_export
from .extraction import fingerprint

FORMAT = "knowledge-author-tags/1"
RULE = {
    "version": "effective-paper-mentions/1",
    "scope": "one_full_effective_snapshot",
    "meaning": "Knowledge mentioned in papers attributed to this author; not expertise or contribution.",
    "minimum_distinct_papers": 1,
    "identity": "exact_source_id_else_paper_local_entity_key",
    "kinds": ["topic", "method", "task", "dataset"],
    "required_relations": ["has_author", "mentions_<kind>"],
    "ranking": "distinct_supporting_papers_desc_then_kind_and_key",
}


def build_author_tags(document):
    """Use only surviving effective edges. Each support retains its four witnesses."""
    validate_effective_export(document)
    authors = {}
    for part in document["papers"]:
        paper_id = part["input"]["openalex_id"]
        entities = {item["content"]["key"]: item for item in part["entities"]}
        roots = {key for key, item in entities.items() if item["content"]["kind"] == "paper"
                 and item["content"].get("source_id") == paper_id}
        mentions = [item for item in part["relations"]
                    if item["content"]["source"] in roots
                    and item["content"]["kind"] in {"mentions_" + kind for kind in RULE["kinds"]}]
        for authorship in part["relations"]:
            relation = authorship["content"]
            if relation["kind"] != "has_author" or relation["source"] not in roots:
                continue
            author = entities[relation["target"]]
            source_id = author["content"].get("source_id")
            # A local key is an extraction reference, not an invented person ID.
            identity = ("source", source_id) if source_id else ("unresolved", paper_id, relation["target"])
            if identity not in authors:
                authors[identity] = dict(
                    author_ref="author-ref:" + fingerprint(identity),
                    source_id=source_id,
                    identity_state="source_identified" if source_id else "paper_local_unresolved",
                    names=set(), paper_ids=set(), tags={},
                )
            entry = authors[identity]
            entry["names"].add(author["content"]["name"])
            entry["paper_ids"].add(paper_id)
            for mention in mentions:
                entity = entities[mention["content"]["target"]]
                content = entity["content"]
                key = (content["kind"], content["key"])
                tag = entry["tags"].setdefault(key, dict(
                    tag_id="knowledge-tag:" + fingerprint(key), kind=key[0], entity_key=key[1],
                    names=set(), supports={},
                ))
                tag["names"].add(content["name"])
                # Duplicate author metadata must not inflate the paper support count.
                support = tag["supports"].setdefault(paper_id, dict(
                    paper_id=paper_id, input_fingerprint=part["origin"]["input_fingerprint"],
                    witnesses={},
                ))
                for role, item in (("author", author), ("authorship", authorship),
                                   ("knowledge", entity), ("mention", mention)):
                    support["witnesses"].setdefault(role, {})[item["candidate_id"]] = deepcopy(item)

    rows = []
    for entry in authors.values():
        entry["names"] = sorted(entry["names"])
        entry["paper_ids"] = sorted(entry["paper_ids"])
        tags = []
        for tag in entry["tags"].values():
            tag["names"] = sorted(tag["names"])
            tag["supporting_paper_count"] = len(tag["supports"])
            supports = []
            for paper_id, support in sorted(tag["supports"].items()):
                support["witnesses"] = {
                    role: [items[key] for key in sorted(items)]
                    for role, items in support["witnesses"].items()
                }
                supports.append(support)
            tag["supports"] = supports
            tags.append(tag)
        entry["tags"] = sorted(tags, key=lambda t: (-t["supporting_paper_count"], t["kind"], t["entity_key"]))
        rows.append(entry)
    content = dict(format_version=FORMAT, knowledge_revision=document["revision"],
                   paper_ids=sorted(part["input"]["openalex_id"] for part in document["papers"]),
                   rule=deepcopy(RULE), authors=sorted(rows, key=lambda row: row["author_ref"]))
    return {**content, "revision": fingerprint(content)}
