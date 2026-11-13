"""Atomic, opt-in B batch ledger; never reads A's DB or changes the fixed corpus."""

import json
import os
import re
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .extraction import extract_candidates, fingerprint, load_vocabulary, validate_result
from .models import PaperInput

FORMAT = "knowledge-batches/1"
SNAPSHOT_FORMAT = "knowledge-batch-input/1"


class BatchConflict(ValueError):
    pass


class BatchStoreInvalid(ValueError):
    pass


class BatchInputInvalid(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Batch validation failed")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _prepare(document):
    if not isinstance(document, dict) or document.get("format_version") != "a-paperinput/1":
        raise BatchInputInvalid([dict(index=None, reason="Expected a-paperinput/1")])
    if (type(document.get("batch_id")) is not int or document["batch_id"] < 1
            or not isinstance(document.get("batch_code"), str) or not document["batch_code"].strip()):
        raise BatchInputInvalid([dict(index=None, reason="Missing batch identity")])
    items, excluded = document.get("items"), document.get("excluded")
    if (not isinstance(items, list) or not isinstance(excluded, list)
            or any(type(document.get(k)) is not int for k in ("total_papers", "exported_papers", "excluded_papers"))
            or document["exported_papers"] != len(items) or document["excluded_papers"] != len(excluded)
            or document["total_papers"] != len(items) + len(excluded)):
        raise BatchInputInvalid([dict(index=None, reason="Batch counts do not match items and excluded")])
    vocabulary = load_vocabulary()
    unique, errors, repeated = {}, [], 0
    for index, raw in enumerate(items):
        try:
            if not isinstance(raw, dict):
                raise ValueError("Paper input must be an object")
            paper = PaperInput(**raw)
            if not isinstance(paper.openalex_id, str) or not re.fullmatch(r"https://openalex.org/W\d+", paper.openalex_id):
                raise ValueError("Expected canonical OpenAlex paper ID")
            for value in (paper.title, paper.abstract, paper.venue, paper.source_url, paper.dataset_id):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Missing paper text, venue, source or dataset")
            if type(paper.year) is not int or not 1 <= paper.year <= 9999:
                raise ValueError("Invalid publication year")
            if urlparse(paper.source_url).scheme not in {"http", "https"} or not urlparse(paper.source_url).netloc:
                raise ValueError("Invalid paper source URL")
            if not isinstance(paper.authorships, list) or any(not isinstance(a, dict) for a in paper.authorships):
                raise ValueError("Invalid authorships")
            # Normalize only the projection's dataset identity. The untouched A
            # document is archived separately for original batch provenance.
            paper.dataset_id = "b-paper:" + paper.openalex_id.rsplit("/", 1)[-1]
            result = extract_candidates(paper, vocabulary)
            validate_result(paper, result)
            value = asdict(paper)
            previous = unique.get(paper.openalex_id)
            if previous is not None:
                if previous != value:
                    raise ValueError("Conflicting paper versions within one batch")
                repeated += 1
            else:
                unique[paper.openalex_id] = value
        except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            errors.append(dict(index=index, reason=str(exc)[:300]))
    if errors:
        raise BatchInputInvalid(errors)
    return [unique[k] for k in sorted(unique)], repeated


def _snapshot(state):
    providers = {}
    for batch in sorted(state["batches"], key=lambda b: b["sequence"]):
        if not batch["active"]:
            continue
        for raw in batch["papers"]:
            providers.setdefault(raw["openalex_id"], []).append((batch, raw))
    papers = []
    for identifier, versions in sorted(providers.items()):
        batch, raw = versions[-1]
        papers.append(dict(input=deepcopy(raw), input_fingerprint=fingerprint(raw),
            selected_batch=batch["batch_code"],
            providers=[dict(batch_id=b["batch_id"], batch_code=b["batch_code"],
                dataset_id=b["document"].get("dataset_id"), handoff_digest=b["handoff_digest"])
                for b, _ in versions]))
    content = dict(format_version=SNAPSHOT_FORMAT, papers=papers, paper_count=len(papers))
    return {**content, "revision": fingerprint(content)}


class BatchRegistry:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return dict(format_version=FORMAT, revision=0, batches=[], events=[])
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            state = document["payload"]
            if (document["sha256"] != fingerprint(state) or state["format_version"] != FORMAT
                    or type(state["revision"]) is not int or state["revision"] < 0
                    or not isinstance(state["batches"], list) or not isinstance(state["events"], list)
                    or state["revision"] != len(state["events"])):
                raise ValueError("Invalid ledger structure")
            codes, ids = set(), set()
            for index, batch in enumerate(state["batches"], 1):
                if (batch["batch_code"] in codes or batch["batch_id"] in ids
                        or type(batch["active"]) is not bool or batch["sequence"] != index
                        or batch["handoff_digest"] != fingerprint(batch["document"])):
                    raise ValueError("Invalid stored batch identity")
                prepared, _ = _prepare(batch["document"])
                if (batch["papers"] != prepared or batch["batch_code"] != batch["document"]["batch_code"]
                        or batch["batch_id"] != batch["document"]["batch_id"]):
                    raise ValueError("Stored batch differs from source")
                codes.add(batch["batch_code"])
                ids.add(batch["batch_id"])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BatchStoreInvalid("Batch ledger is invalid; original file preserved") from exc
        return state

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise BatchConflict("Batch ledger is busy; retry after the current writer finishes") from exc
        temporary = None
        try:
            state = self.read()
            before = deepcopy(state)
            yield state
            if before == state:
                return
            state["revision"] = len(state["events"])
            body = dict(payload=state, sha256=fingerprint(state))
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(body, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            handle.close()
            lock.unlink()

    def snapshot(self):
        return _snapshot(self.read())

    def ingest(self, document, *, expected_revision=None):
        digest = fingerprint(document)
        with self._transaction() as state:
            if expected_revision is not None and state["revision"] != expected_revision:
                raise BatchConflict("批次记录已更新，请刷新后重试")
            if isinstance(document, dict):
                existing = next((b for b in state["batches"] if b["batch_code"] == document.get("batch_code")
                                 or b["batch_id"] == document.get("batch_id")), None)
                if existing:
                    if existing["handoff_digest"] != digest:
                        raise BatchConflict("Successful batch identity is immutable; use a new batch")
                    return dict(status="unchanged" if existing["active"] else "withdrawn", accepted=0,
                        snapshot_revision=_snapshot(state)["revision"], original_receipt=deepcopy(existing["receipt"]))
            try:
                papers, repeated = _prepare(document)
            except BatchInputInvalid as exc:
                total = len(document.get("items", [])) if isinstance(document, dict) and isinstance(document.get("items"), list) else 0
                invalid_rows = len({e["index"] for e in exc.errors if e["index"] is not None})
                result = dict(status="failed", accepted=0, new=0, updated=0, duplicates=0,
                    failed=len(exc.errors), not_applied=max(0, total-invalid_rows), errors=exc.errors,
                    snapshot_revision=_snapshot(state)["revision"])
                state["events"].append(dict(action="ingest_failed", occurred_at=_now(),
                    batch_code=document.get("batch_code") if isinstance(document, dict) else None,
                    handoff_digest=digest, result=deepcopy(result)))
                return result
            before = {p["input"]["openalex_id"]: p["input"] for p in _snapshot(state)["papers"]}
            new = sum(p["openalex_id"] not in before for p in papers)
            updated = sum(p["openalex_id"] in before and p != before[p["openalex_id"]] for p in papers)
            result = dict(status="accepted", batch_code=document["batch_code"], accepted=len(papers),
                new=new, updated=updated, duplicates=repeated+len(papers)-new-updated,
                failed=0, not_applied=0, upstream_excluded=len(document["excluded"]))
            batch = dict(batch_id=document["batch_id"], batch_code=document["batch_code"],
                sequence=len(state["batches"])+1, active=True, handoff_digest=digest,
                document=deepcopy(document), papers=papers, receipt=result)
            state["batches"].append(batch)
            result["snapshot_revision"] = _snapshot(state)["revision"]
            state["events"].append(dict(action="ingest", occurred_at=_now(), result=deepcopy(result)))
            return deepcopy(result)

    def withdraw(self, batch_code, *, expected_revision=None):
        with self._transaction() as state:
            if expected_revision is not None and state["revision"] != expected_revision:
                raise BatchConflict("批次记录已更新，请刷新后重试")
            batch = next((b for b in state["batches"] if b["batch_code"] == batch_code), None)
            if batch is None:
                raise LookupError("Unknown batch")
            if not batch["active"]:
                return dict(status="unchanged", snapshot_revision=_snapshot(state)["revision"])
            before = {p["input"]["openalex_id"]: p["input"] for p in _snapshot(state)["papers"]}
            batch["active"] = False
            snapshot = _snapshot(state)
            after = {p["input"]["openalex_id"]: p["input"] for p in snapshot["papers"]}
            affected = {p["openalex_id"] for p in batch["papers"]}
            result = dict(status="withdrawn", batch_code=batch_code, removed=len(affected-after.keys()),
                retained=len(affected & after.keys()),
                restored=sum(before[k] != after[k] for k in affected & after.keys()),
                snapshot_revision=snapshot["revision"])
            state["events"].append(dict(action="withdraw", occurred_at=_now(), result=deepcopy(result)))
            return result

    def workspace(self, feedback_path, vocabulary=None, *, source_store=None):
        """An isolated current workspace for the existing effective exporter."""
        from .feedback import FeedbackStore, KnowledgeFeedback
        vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
        snapshot = self.snapshot()
        papers = [PaperInput(**p["input"]) for p in snapshot["papers"]]
        results = {p.openalex_id: extract_candidates(p, vocabulary) for p in papers}
        from .batch_sources import BatchSources
        sources = (source_store or BatchSources(self.path)).records(papers, vocabulary)
        workspace = KnowledgeFeedback(papers, results, {}, vocabulary, FeedbackStore(feedback_path), source_records=sources)
        workspace.batch_snapshot_revision = snapshot["revision"]
        return workspace
