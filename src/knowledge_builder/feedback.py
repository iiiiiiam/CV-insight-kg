"""Automatic knowledge views and feedback decisions, independent of web frameworks.

Original extraction/review archives remain untouched. Decisions are bound to the
original candidate and input; vocabulary additions remain reproducible rules.
"""

import json
import hmac
import os
import re
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from .extraction import extract_candidates, fingerprint, validate_vocabulary

FORMAT = "knowledge-feedback/1"
STATES = ("open", "resolved", "dismissed")  # Admin queue excludes withdrawn requests.


def _owner_digest(token):
    if token is None:
        return None  # Legacy submissions stay readable, without granting withdrawal rights.
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        raise ValueError("反馈凭证无效")
    return fingerprint(token)


class FeedbackConflict(ValueError):
    pass


class FeedbackStoreInvalid(ValueError):
    pass


def _text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label}不能为空且不能超过{limit}字")
    return value.strip()


def _now():
    return datetime.now(timezone.utc).isoformat()


class FeedbackStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return dict(format_version=FORMAT, revision=0, requests=[], decisions=[], terms=[])
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            data = doc["payload"]
            if doc["sha256"] != fingerprint(data) or data["format_version"] != FORMAT:
                raise ValueError("反馈文件校验或版本不匹配")
            if type(data["revision"]) is not int or data["revision"] < 0:
                raise ValueError("反馈文件版本号无效")
            for key in ("requests", "decisions", "terms"):
                if not isinstance(data[key], list):
                    raise ValueError("反馈文件结构无效")
        except (ValueError, KeyError, TypeError) as exc:
            raise FeedbackStoreInvalid("反馈文件损坏或版本不匹配；原记录保留，请检查存档") from exc
        return data

    @contextmanager
    def transaction(self, expected_revision=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise FeedbackConflict("其他窗口正在保存，请刷新后重试") from exc
        temporary = None
        try:
            data = self.read()
            before = deepcopy(data)
            if expected_revision is not None and data["revision"] != expected_revision:
                raise FeedbackConflict("反馈队列已变化，请刷新后再处理")
            yield data
            if data == before:
                return
            data["revision"] += 1
            doc = {"payload": data, "sha256": fingerprint(data)}
            body = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as out:
                temporary = Path(out.name)
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            handle.close()
            lock.unlink()


class KnowledgeFeedback:
    def __init__(self, papers, results, sessions, vocabulary, store, *, source_records=None):
        self.papers = {p.openalex_id: p for p in papers}
        self.results = results
        self.sessions = sessions
        self.vocabulary = vocabulary
        self.store = store
        self.source_records = source_records
        if set(results) != set(self.papers) or any(
            r.vocabulary_fingerprint != fingerprint(vocabulary) for r in results.values()
        ):
            raise FeedbackConflict("基础词表或输入已更新，请重新读取")

    def _vocabulary(self, data):
        vocabulary = deepcopy(self.vocabulary)
        for record in data["terms"]:
            term = record["term"]
            existing = next((t for t in vocabulary["terms"]
                             if (t["kind"], t["key"]) == (term["kind"], term["key"])), None)
            if existing is None:
                vocabulary["terms"].append(deepcopy(term))
            else:
                aliases = {a.casefold() for a in existing["aliases"]}
                existing["aliases"].extend(a for a in term["aliases"] if a.casefold() not in aliases)
        if data["terms"]:
            vocabulary["version"] += "+feedback." + fingerprint(vocabulary["terms"])[:12]
        validate_vocabulary(vocabulary)
        return vocabulary

    def _extract(self, paper, vocabulary):
        if self.source_records is None:
            return extract_candidates(paper, vocabulary), None
        from .source_enrichment import extract_with_sources
        return extract_with_sources(paper, vocabulary, self.source_records.get(paper.openalex_id, []))

    def _material(self, paper_id, data, *, with_provenance=False):
        if paper_id not in self.papers:
            raise LookupError("该论文尚未纳入当前知识输入")
        paper = self.papers[paper_id]
        vocabulary = self._vocabulary(data)
        result, enrichment = self._extract(paper, vocabulary)
        items = {}
        for c in result.entities:
            items[c.candidate_id] = dict(candidate_id=c.candidate_id, content=asdict(c.entity),
                                         evidence=[asdict(e) for e in c.evidence])
        for c in result.relations:
            items[c.candidate_id] = dict(candidate_id=c.candidate_id,
                content=dict(source=c.source, kind=c.kind, target=c.target),
                evidence=[asdict(e) for e in c.evidence])
        signatures = {key: fingerprint(item) for key, item in items.items()}
        provenance = {key: dict(generation="automatic", review_state="automatic", rule_adjusted=False)
                      for key in items} if with_provenance else None
        if with_provenance and data["terms"]:
            original_result, _ = self._extract(paper, self.vocabulary)
            original_items = {c.candidate_id: dict(candidate_id=c.candidate_id, content=asdict(c.entity),
                evidence=[asdict(e) for e in c.evidence]) for c in original_result.entities}
            original_items.update({c.candidate_id: dict(candidate_id=c.candidate_id,
                content=dict(source=c.source, kind=c.kind, target=c.target), evidence=[asdict(e) for e in c.evidence])
                for c in original_result.relations})
            for key, info in provenance.items():
                info["rule_adjusted"] = signatures[key] != fingerprint(original_items.get(key))
        # Carry over actual legacy edits, not the unchanged baseline snapshots:
        # new vocabulary may add evidence to an already-existing candidate.
        session = self.sessions.get(paper_id)
        excluded = set()
        if session is not None:
            original = session.original
            baseline = {
                c.candidate_id: dict(content=asdict(c.entity), evidence=[asdict(e) for e in c.evidence])
                for c in original.entities
            }
            baseline.update({
                c.candidate_id: dict(content=dict(source=c.source, kind=c.kind, target=c.target),
                                     evidence=[asdict(e) for e in c.evidence])
                for c in original.relations
            })
            for item in session.items:
                if item.candidate_id not in items:
                    continue
                if item.status == "rejected":
                    excluded.add(item.candidate_id)
                else:
                    previous = baseline[item.candidate_id]
                    reviewed_content = asdict(item.content)
                    reviewed_evidence = [asdict(e) for e in item.evidence]
                    if reviewed_content != previous["content"]:
                        items[item.candidate_id]["content"] = reviewed_content
                    if reviewed_evidence != previous["evidence"]:
                        items[item.candidate_id]["evidence"] = reviewed_evidence
                    if provenance is not None:
                        current = items[item.candidate_id]
                        if item.status == "confirmed" and current["content"] == reviewed_content and current["evidence"] == reviewed_evidence:
                            provenance[item.candidate_id]["review_state"] = "human_confirmed"
                        elif reviewed_content != previous["content"] or reviewed_evidence != previous["evidence"]:
                            provenance[item.candidate_id]["review_state"] = "human_corrected"
        for decision in data["decisions"]:
            key = decision["candidate_id"]
            if (decision["paper_id"] != paper_id or key not in items or
                decision["input_fingerprint"] != result.input_fingerprint or
                decision["candidate_fingerprint"] != signatures[key]):
                continue
            if decision["action"] == "exclude":
                excluded.add(key)
            elif decision["action"] == "rename":
                items[key]["content"]["name"] = decision["name"]
                if provenance is not None:
                    provenance[key]["review_state"] = "human_corrected"
        entities = [item for key, item in items.items() if "key" in item["content"] and key not in excluded]
        keys = {item["content"]["key"] for item in entities}
        relations = [item for key, item in items.items()
                     if "source" in item["content"] and key not in excluded
                     and item["content"]["source"] in keys and item["content"]["target"] in keys]
        public = dict(paper=dict(openalex_id=paper.openalex_id, title=paper.title,
            abstract=paper.abstract, year=paper.year, venue=paper.venue, source_url=paper.source_url),
            entities=entities, relations=relations, vocabulary_version=result.vocabulary_version)
        if enrichment is not None:
            public["source_enrichment"] = enrichment
        public["revision"] = fingerprint(public)
        if with_provenance:
            return public, items, signatures, result, provenance
        return public, items, signatures, result

    def list_papers(self):
        return [dict(paper_id=p.openalex_id, title=p.title, year=p.year, venue=p.venue)
                for p in self.papers.values()]

    def view(self, paper_id):
        return self._material(paper_id, self.store.read())[0]

    def export_effective(self, expected_revision=None):
        from .effective_export import build_effective_export
        return build_effective_export(self, expected_revision=expected_revision)

    def submit(self, paper_id, revision, message, *, candidate_id=None, term=None, owner_token=None):
        message = _text(message, "问题描述")
        owner_digest = _owner_digest(owner_token)
        if bool(candidate_id) == bool(term):
            raise ValueError("请选择具体条目，或填写一个遗漏名称")
        with self.store.transaction() as data:
            public, items, signatures, result = self._material(paper_id, data)
            if public["revision"] != revision:
                raise FeedbackConflict("论文信息已更新，请刷新后提交")
            visible = {i["candidate_id"] for i in public["entities"] + public["relations"]}
            requested = None
            if candidate_id:
                if candidate_id not in visible:
                    raise ValueError("该条目已不可见，请刷新论文")
                context = deepcopy(items[candidate_id])
            else:
                term = _text(term, "遗漏名称", 200)
                paper = self.papers[paper_id]
                found = next(((field, m) for field in ("title", "abstract")
                    for m in re.finditer(re.escape(term), getattr(paper, field) or "", re.IGNORECASE)), None)
                if found is None:
                    raise ValueError("标题或摘要中未找到该名称，请填写原文中的写法")
                field, match = found
                requested = term
                context = dict(field=field, quote=match.group(), start=match.start(), end=match.end())
            for request in data["requests"]:
                if (request["status"] == "open" and request["paper_id"] == paper_id
                    and request["candidate_id"] == candidate_id
                    and (request["term"] or "").casefold() == (requested or "").casefold()
                    and request["input_fingerprint"] == result.input_fingerprint
                    and request.get("owner_digest") == owner_digest
                    and request["resource_revision"] == revision):
                    return dict(id=request["id"], status="open", duplicate=True)
            now = _now()
            request = dict(id=uuid4().hex, paper_id=paper_id, paper_title=public["paper"]["title"],
                candidate_id=candidate_id, term=requested, message=message, context=context,
                input_fingerprint=result.input_fingerprint, resource_revision=revision,
                candidate_fingerprint=signatures.get(candidate_id), status="open",
                created_at=now, updated_at=now, resolution=None, owner_digest=owner_digest)
            data["requests"].append(request)
            return dict(id=request["id"], status="open", duplicate=False)

    def queue(self):
        data = self.store.read()
        requests = [r for r in data["requests"] if r["status"] != "withdrawn"]
        return dict(revision=data["revision"], requests=[{k: v for k, v in r.items() if k != "owner_digest"}
            for r in reversed(requests)],
            counts={state: sum(r["status"] == state for r in requests) for state in STATES},
            terms=data["terms"])

    def status(self, identifier):
        request = next((r for r in self.store.read()["requests"] if r["id"] == identifier), None)
        if request is None:
            raise LookupError("未找到反馈")
        # No public message, identity, decision reason or historical snapshots.
        return {key: request[key] for key in ("id", "status", "updated_at")}

    def withdraw(self, identifier, *, owner_token):
        owner_digest = _owner_digest(owner_token)
        with self.store.transaction() as data:
            request = next((r for r in data["requests"] if r["id"] == identifier), None)
            if (request is None or not owner_digest or not request.get("owner_digest")
                or not hmac.compare_digest(request["owner_digest"], owner_digest)):
                raise LookupError("未找到可由当前浏览器撤回的反馈")
            if request["status"] == "withdrawn":
                return dict(id=identifier, status="withdrawn")
            if request["status"] != "open":
                raise FeedbackConflict("反馈已被管理员处理，不能撤回；原处理记录保留")
            request["status"] = "withdrawn"
            request["updated_at"] = _now()
            return dict(id=identifier, status="withdrawn")

    def resolve(self, identifier, *, revision, action, reason, reviewer,
                name=None, kind=None, aliases=None, source_url=None):
        reason = _text(reason, "处理理由")
        reviewer = _text(reviewer, "管理员账号", 200)
        if action not in ("dismiss", "exclude", "rename", "add_term"):
            raise ValueError("不支持的处理方式")
        with self.store.transaction(revision) as data:
            request = next((r for r in data["requests"] if r["id"] == identifier), None)
            if request is None:
                raise LookupError("未找到反馈")
            if request["status"] != "open":
                raise FeedbackConflict("该反馈已处理或撤回，请刷新")
            public, items, signatures, result = self._material(request["paper_id"], data)
            key = request["candidate_id"]
            if action != "dismiss" and (request["input_fingerprint"] != result.input_fingerprint
                or (key and request["candidate_fingerprint"] != signatures.get(key))):
                raise FeedbackConflict("目标原文或提取依据已变化，不能套用旧反馈")
            if action != "dismiss" and key:
                visible = {i["candidate_id"] for i in public["entities"] + public["relations"]}
                if key not in visible or fingerprint(request["context"]) != fingerprint(items[key]):
                    raise FeedbackConflict("该条目已被其他决定更新，请重新核对")
            before = deepcopy(items.get(key))
            now = _now()
            if action in ("rename", "exclude"):
                if not key:
                    raise ValueError("遗漏反馈请补充词条，或说明原因关闭")
                if action == "rename":
                    if "key" not in items[key]["content"]:
                        raise ValueError("关系不支持修改显示名")
                    name = _text(name, "显示名", 300)
                    if name == items[key]["content"]["name"]:
                        raise ValueError("显示名未变化")
                data["decisions"].append(dict(feedback_id=identifier, paper_id=request["paper_id"],
                    candidate_id=key, input_fingerprint=result.input_fingerprint,
                    candidate_fingerprint=signatures[key], action=action, name=name,
                    reviewer=reviewer, reason=reason, occurred_at=now))
            elif action == "add_term":
                if key or kind not in ("topic", "method", "task", "dataset"):
                    raise ValueError("请选择遗漏反馈与有效的词条类别")
                name = _text(name, "规范名称", 200)
                parsed = urlparse(source_url or "")
                if parsed.scheme not in ("https", "http") or not parsed.netloc:
                    raise ValueError("请填写可追溯的公开来源地址")
                aliases = aliases or [request["context"]["quote"]]
                if not isinstance(aliases, list) or not 1 <= len(aliases) <= 8:
                    raise ValueError("请提供 1—8 个必要别名")
                aliases = [_text(a, "别名", 200) for a in aliases]
                proposed = self._vocabulary(data)
                existing = next((t for t in proposed["terms"]
                                 if t["kind"] == kind and t["name"].casefold() == name.casefold()), None)
                if existing is not None:
                    known = {a.casefold() for a in existing["aliases"]}
                    aliases = [a for a in aliases if a.casefold() not in known]
                    if not aliases:
                        raise ValueError("这些写法已在词表中，请说明其他问题或核对匹配边界")
                    term = dict(key=existing["key"], kind=kind, name=existing["name"], aliases=aliases)
                    existing["aliases"].extend(aliases)
                else:
                    term = dict(key="feedback-" + fingerprint([kind, name.casefold()])[:16],
                                kind=kind, name=name, aliases=aliases)
                    proposed["terms"].append(term)
                validate_vocabulary(proposed)
                check, _ = self._extract(self.papers[request["paper_id"]], proposed)
                context = request["context"]
                if not any(c.entity.key == kind + ":term:" + term["key"] and any(
                    proof.field == context["field"] and proof.start == context["start"]
                    and proof.end == context["end"] for proof in c.evidence) for c in check.entities):
                    raise ValueError("新别名没有实际命中该论文，请核对原文与边界")
                data["terms"].append(dict(term=term, feedback_id=identifier, source_url=source_url,
                    reviewer=reviewer, reason=reason, created_at=now))
            request["status"] = "dismissed" if action == "dismiss" else "resolved"
            request["updated_at"] = now
            after = self._material(request["paper_id"], data)[1].get(key)
            shown = self._material(request["paper_id"], data)[0]
            request["resolution"] = dict(action=action, reason=reason, reviewer=reviewer,
                occurred_at=now, before=before, after=deepcopy(after),
                visible_after=key in {i["candidate_id"] for i in shown["entities"] + shown["relations"]})
            return dict(id=identifier, status=request["status"])

    def reopen(self, identifier, *, revision, reviewer):
        reviewer = _text(reviewer, "管理员账号", 200)
        with self.store.transaction(revision) as data:
            request = next((r for r in data["requests"] if r["id"] == identifier), None)
            if request is None:
                raise LookupError("未找到反馈")
            if request["status"] not in ("resolved", "dismissed"):
                raise FeedbackConflict("只能撤回已处理的反馈；待处理或用户已撤回的反馈不能执行此操作")
            # Remove this feedback's effects, never restore a whole historical store.
            previous = deepcopy(data)
            data["decisions"] = [d for d in data["decisions"] if d["feedback_id"] != identifier]
            data["terms"] = [t for t in data["terms"] if t["feedback_id"] != identifier]
            if len(data["terms"]) != len(previous["terms"]):
                # A later correction may rely on the newly introduced term/alias.
                # Keep it intact: undo that dependent correction first.
                for paper_id in {d["paper_id"] for d in data["decisions"]}:
                    if paper_id not in self.papers:
                        continue
                    _, _, before_signatures, before_result = self._material(paper_id, previous)
                    _, _, after_signatures, after_result = self._material(paper_id, data)
                    for decision in data["decisions"]:
                        if decision["paper_id"] != paper_id:
                            continue
                        key = decision["candidate_id"]
                        if (decision["input_fingerprint"] == before_result.input_fingerprint
                            and decision["candidate_fingerprint"] == before_signatures.get(key)
                            and (decision["input_fingerprint"] != after_result.input_fingerprint
                                 or decision["candidate_fingerprint"] != after_signatures.get(key))):
                            raise FeedbackConflict("其他处理依赖此词条，请先撤回依赖它的处理，再撤回补词")
            now = _now()
            request.setdefault("processing_history", []).append(dict(
                resolution=deepcopy(request["resolution"]), reopened_by=reviewer, reopened_at=now))
            request["resolution"] = None
            request["status"] = "open"
            request["updated_at"] = now
            return dict(id=identifier, status="open")
