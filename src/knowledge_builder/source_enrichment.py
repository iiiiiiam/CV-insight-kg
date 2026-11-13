"""Experimental source-backed vocabulary overlays; legacy input/schema stay intact.

Source classifications remain in a separate envelope. Only literal title/abstract
matches enter the existing seven-relation extractor, never fake text evidence.
"""

import re
from copy import deepcopy
from dataclasses import asdict

from .extraction import extract_candidates, fingerprint, validate_result, validate_vocabulary
from .enrichment_sources import same_paper
from .curated_vocabulary import merge_curated_vocabulary
from .text_signals import explicit_signals, VERSION as TEXT_RULE_VERSION
from .research_directions import classify_directions

FORMAT = "source-enrichment-experiment/1"
TASK_PATTERN = re.compile(r"(?:object detection|instance segmentation|semantic segmentation|image segmentation|image classification|depth estimation|object tracking)$", re.I)
METRIC_NAMES = {"fid", "fréchet inception distance (fid)", "frechet inception distance", "psnr", "ssim", "map", "mean average precision"}


def text_matches(paper, alias):
    pattern = r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])"
    for field in ("title", "abstract"):
        text = getattr(paper, field) or ""
        flags = 0 if alias in {"CLIP", "ViT"} else re.I
        for match in re.finditer(pattern, text, flags):
            yield dict(field=field, quote=match.group(), start=match.start(), end=match.end())


def dataset_context(paper, alias):
    """An external benchmark label plus an explicit nearby dataset statement."""
    for proof in text_matches(paper, alias):
        text = getattr(paper, proof["field"]) or ""
        boundary = text.rfind(". ", 0, proof["start"])
        left = max(boundary + 2 if boundary >= 0 else 0, proof["start"] - 120)
        end = text.find(". ", proof["end"])
        right = min(end if end >= 0 else len(text), proof["end"] + 120)
        if re.search(r"\b(?:data\s*sets?|corpus|corpora)\b", text[left:right], re.I):
            return True
    return False


def _analyze_sources(paper, vocabulary, records, *, fallback=False):
    validate_vocabulary(vocabulary)
    overlay = deepcopy(vocabulary)
    curated = []
    if fallback:
        overlay, curated = merge_curated_vocabulary(vocabulary, paper)
    known = {alias.casefold(): term for term in overlay["terms"] for alias in term["aliases"]}
    by_name = {(t["kind"], t["name"].casefold()): t for t in overlay["terms"]}
    facts, accepted, skipped = [], [], []

    def propose(kind, name, alias, record, path, basis):
        if kind not in ("topic", "method", "task", "dataset") or not isinstance(name, str) or not isinstance(alias, str):
            return
        name, alias = name.strip(), alias.strip()
        if kind == "method" and name.casefold() == "inpainting":
            kind = "task"
        if not name or not alias or len(name) > 200 or len(alias) > 200:
            return
        if kind == "method" and name.casefold() in METRIC_NAMES | {"embedding"}:
            skipped.append(dict(kind=kind, name=name, reason="source_metric_or_generic_label_not_method", source=record["source"]))
            return
        proofs = list(text_matches(paper, alias))
        if not proofs:
            skipped.append(dict(kind=kind, name=name, reason="not_in_frozen_title_or_abstract", source=record["source"]))
            return
        existing = known.get(alias.casefold())
        target = by_name.get((kind, name.casefold()))
        if existing is None and kind == "dataset":
            for known_alias, term in known.items():
                if term["kind"] == "dataset" and re.fullmatch(re.escape(known_alias) + r"\s+\d{2,4}", alias, re.I):
                    target = term
                    break
        if existing is not None and (existing["kind"] != kind or (target is not None and target is not existing)):
            skipped.append(dict(kind=kind, name=name, reason="alias_type_or_identity_conflict", source=record["source"]))
            return
        if existing is not None:
            target = existing
        elif target is not None:
            target["aliases"].append(alias)
            known[alias.casefold()] = target
        else:
            target = dict(key="source-" + fingerprint([kind, name.casefold()])[:16], kind=kind, name=name, aliases=[alias])
            overlay["terms"].append(target)
            known[alias.casefold()] = target
            by_name[(kind, name.casefold())] = target
        accepted.append(dict(kind=kind, name=target["name"], key=target["key"], alias=alias, basis=basis,
            source=record["source"], source_url=record["url"], source_digest=record["digest"],
            source_path=path, matched_evidence=proofs))

    for record in records:
        payload = record["payload"]
        if record["digest"] != fingerprint(payload):
            raise ValueError("Supplement checksum differs from its payload")
        if record["source"] == "openalex":
            if payload.get("id") != paper.openalex_id:
                raise ValueError("Supplement belongs to another OpenAlex paper")
            for i, topic in enumerate(payload.get("topics") or []):
                if not isinstance(topic, dict) or not isinstance(topic.get("display_name"), str) or not topic.get("id"):
                    continue
                classification = dict(kind="topic", name=topic["display_name"], source_id=topic["id"],
                    score=topic.get("score"), basis="source_classification", source="openalex", source_url=record["url"],
                    source_path=["topics", i], source_digest=record["digest"])
                # OpenAlex's subfield is ABOVE the topic, not a finer topic.
                # Optional source metadata keeps the eight-entity/seven-relation
                # contract intact and never pretends to be a literal text quote.
                hierarchy = {}
                for level in ("subfield", "field", "domain"):
                    parent = topic.get(level)
                    if not isinstance(parent, dict):
                        continue
                    identifier, name = parent.get("id"), parent.get("display_name")
                    if (isinstance(identifier, str) and identifier.strip()
                            and isinstance(name, str) and name.strip()):
                        hierarchy[level] = dict(source_id=identifier.strip(), name=name.strip(),
                                                source_path=["topics", i, level])
                if hierarchy:
                    classification["hierarchy"] = hierarchy
                facts.append(classification)
                # Literal mentions may use the existing relation contract. The rest
                # stay classifications: do not turn an inferred topic into a quote.
                propose("topic", topic["display_name"], topic["display_name"], record, ["topics", i], "typed_source_topic_and_text")
            for i, keyword in enumerate(payload.get("keywords") or []):
                name = keyword.get("display_name") if isinstance(keyword, dict) else None
                if not isinstance(name, str):
                    continue
                match = known.get(name.casefold())
                if match:
                    propose(match["kind"], match["name"], name, record, ["keywords", i], "keyword_known_type_and_text")
                elif TASK_PATTERN.search(name) and len(name.split()) <= 8:
                    propose("task", name, name, record, ["keywords", i], "keyword_task_suffix_and_text")
                else:
                    skipped.append(dict(name=name, reason="keyword_type_unknown", source="openalex"))
        elif record["source"] == "paperswithcode":
            if not same_paper(paper, payload):
                raise ValueError("Catalog supplement belongs to another paper")
            for group, kind in (("tasks", "task"), ("methods", "method")):
                for i, item in enumerate(payload.get(group) or []):
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        propose(kind, item["name"], item["name"], record, [group, i], "typed_catalog_and_text")
            for i, mention in enumerate(payload.get("abstract_mentions") or []):
                if not isinstance(mention, dict):
                    continue
                # An annotation is not itself proof in our frozen input. Locate its
                # surface anew; external abstract offsets are not blindly reused.
                propose(mention.get("entity_type"), mention.get("name"), mention.get("surface"), record,
                        ["abstract_mentions", i], "typed_catalog_surface_and_text")
            # Benchmark labels often append split/task descriptions (e.g. COCO
            # (val2017)). Prefer known dataset identities; otherwise require the
            # complete label, or its parenthesis-free name, in our frozen text.
            for i, label in enumerate(payload.get("evaluated_benchmarks") or []):
                if not isinstance(label, str) or not label.strip():
                    continue
                matches = [t for t in overlay["terms"] if t["kind"] == "dataset"
                           and any(re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", label, re.I)
                                   for a in t["aliases"])]
                if matches:
                    for term in matches:
                        for alias in term["aliases"]:
                            if list(text_matches(paper, alias)):
                                propose("dataset", term["name"], alias, record, ["evaluated_benchmarks", i],
                                        "catalog_benchmark_known_dataset_and_text")
                else:
                    name = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
                    # A benchmark may be a task, suite or metric. Its field alone
                    # cannot establish a new dataset type; require a typed entity
                    # or the maintained dataset registry instead.
                    if name and dataset_context(paper, name):
                        propose("dataset", name, name, record, ["evaluated_benchmarks", i],
                                "catalog_benchmark_and_explicit_dataset_context")
                    else:
                        skipped.append(dict(name=name, reason="benchmark_dataset_type_unknown", source=record["source"]))
    facts.extend(classify_directions(paper, records))
    rule_signals = []
    if fallback:
        local = dict(source="text_rules", url=paper.source_url, digest=fingerprint(asdict(paper)))
        for signal in explicit_signals(paper):
            start = len(accepted)
            propose(signal["kind"], signal["name"], signal["alias"], local, [signal["field"]], signal["rule"])
            if len(accepted) > start:
                rule_signals.append(signal)
    if overlay != vocabulary:
        overlay["version"] += "+sources." + fingerprint(overlay["terms"])[:12]
    validate_vocabulary(overlay)
    before = extract_candidates(paper, vocabulary)
    after = extract_candidates(paper, overlay)
    # A more specific source alias can occupy a longer span in the old matcher.
    # Enrichment is additive: retain the baseline candidates and their proofs.
    for field in ("entities", "relations"):
        combined = {c.candidate_id: deepcopy(c) for c in getattr(before, field)}
        for candidate in getattr(after, field):
            existing = combined.get(candidate.candidate_id)
            if existing is None:
                combined[candidate.candidate_id] = candidate
            else:
                existing.evidence.extend(p for p in candidate.evidence if p not in existing.evidence)
        setattr(after, field, list(combined.values()))
    validate_result(paper, after)
    base_ids = {c.candidate_id for c in before.entities}
    analysis = dict(format_version=FORMAT, paper_id=paper.openalex_id, title=paper.title,
                input_fingerprint=before.input_fingerprint, source_classifications=facts,
                accepted_signals=accepted, ignored_signals=skipped,
                text_rule_version=TEXT_RULE_VERSION, text_signals=rule_signals,
                fallback_matches=[dict(**term, matched_evidence=list(text_matches(paper, term["alias"])))
                                  for term in curated if list(text_matches(paper, term["alias"]))],
                source_records=[{k: r[k] for k in ("source", "url", "fetched_at", "digest")} for r in records],
                experimental_vocabulary=overlay,
                baseline=asdict(before), enriched=asdict(after),
                added_entities=[asdict(c.entity) for c in after.entities if c.candidate_id not in base_ids])
    return analysis, after


def analyze_sources(paper, vocabulary, records, *, fallback=False):
    return _analyze_sources(paper, vocabulary, records, fallback=fallback)[0]


def extract_with_sources(paper, vocabulary, records):
    """Use frozen source records, without HTTP during reading or feedback handling."""
    analysis, result = _analyze_sources(paper, vocabulary, records, fallback=True)
    details = {key: analysis[key] for key in
               ("source_classifications", "accepted_signals", "source_records", "added_entities", "fallback_matches", "text_signals")}
    return result, details
