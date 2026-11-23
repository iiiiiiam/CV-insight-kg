"""Bounded, evidence-based summaries of one immutable published snapshot."""
import json
from datetime import datetime, timezone

from .search import normalize


class ResearchReports:
    @staticmethod
    def _identity(row):
        return "source_identified" if row.get("source_id") else (
            "paper_local_unresolved" if ":unresolved:" in row["id"] else "entity_id_only")

    @staticmethod
    def _summary_meta(tx, batch):
        return dict(tx.run("MATCH (b:CVBatch {id:$batch}) RETURN properties(b) AS b",
                           batch=batch).single()["b"])

    def _ranked_entities(self, tx, batch, filters, kind, limit):
        params = dict(normalize(filters), batch=batch, limit=limit)
        scope = "MATCH (p:CVEntity) WHERE " + self.where(normalize(filters))
        if kind == "author":
            scope += " MATCH (p)-[:CV_LINK {kind:'has_author'}]->(e:CVEntity {batch_id:$batch,kind:'author'})"
        else:
            scope += """ MATCH (p)-[:CV_LINK {kind:'has_author'}]->(:CVEntity {batch_id:$batch,kind:'author'})
                -[aff:CV_LINK {kind:'affiliated_with'}]->(e:CVEntity {batch_id:$batch,kind:'institution'})
                WHERE p.id IN aff.paper_ids"""
        coverage = dict(tx.run(scope + """ RETURN count(DISTINCT e) AS total,count(DISTINCT p) AS covered,
            count(DISTINCT CASE WHEN coalesce(e.source_id,'')<>'' THEN e.id END) AS source_identified""", params).single())
        items = [dict(r) for r in tx.run(scope + """ RETURN e.id AS id,e.source_id AS source_id,
            e.name AS name,count(DISTINCT p) AS paper_count ORDER BY paper_count DESC,id LIMIT $limit""", params)]
        for item in items:
            item["identity_state"] = self._identity(item)
        return dict(items=items, total=coverage["total"], truncated=coverage["total"] > limit,
                    source_identified_total=coverage["source_identified"],
                    without_source_id_total=coverage["total"]-coverage["source_identified"],
                    papers_with_relation=coverage["covered"], limit=limit,
                    basis="stable_id; distinct_papers; same-paper affiliation evidence required" if kind == "institution"
                    else "stable_id; has_author; distinct_papers; names do not merge identities")

    def _partners(self, tx, batch, anchor, kind, filters, page, page_size, paper_limit):
        from .repository import GraphError
        exists = tx.run("MATCH (a:CVEntity {batch_id:$batch,id:$anchor,kind:$kind}) RETURN a.name AS name,a.source_id AS source_id",
                        batch=batch, anchor=anchor, kind=kind).single()
        if not exists:
            raise GraphError(404, "AUTHOR_NOT_FOUND" if kind == "author" else "INSTITUTION_NOT_FOUND", "当前发布批次中不存在该稳定实体 ID")
        f = normalize(filters)
        params = dict(f, batch=batch, anchor=anchor, skip=(page-1)*page_size, limit=page_size)
        base = "MATCH (p:CVEntity) WHERE " + self.where(f)
        if kind == "author":
            anchored = base + """ MATCH (p)-[:CV_LINK {kind:'has_author'}]->(a:CVEntity {batch_id:$batch,id:$anchor,kind:'author'})"""
            pairs = anchored + """ MATCH (p)-[:CV_LINK {kind:'has_author'}]->(other:CVEntity {batch_id:$batch,kind:'author'})
                WHERE other.id<>$anchor"""
        else:
            anchored = base + """ MATCH (p)-[:CV_LINK {kind:'has_author'}]->(:CVEntity {batch_id:$batch,kind:'author'})
                -[aff:CV_LINK {kind:'affiliated_with'}]->(a:CVEntity {batch_id:$batch,id:$anchor,kind:'institution'})
                WHERE p.id IN aff.paper_ids"""
            pairs = anchored + """ MATCH (p)-[:CV_LINK {kind:'has_author'}]->(:CVEntity {batch_id:$batch,kind:'author'})
                -[aff2:CV_LINK {kind:'affiliated_with'}]->(other:CVEntity {batch_id:$batch,kind:'institution'})
                WHERE other.id<>$anchor AND p.id IN aff2.paper_ids"""
        own_count = tx.run(anchored + " RETURN count(DISTINCT p) AS n", params).single()["n"]
        total = tx.run(pairs + " RETURN count(DISTINCT other) AS n", params).single()["n"]
        rows = tx.run(pairs + """ RETURN other.id AS id,other.name AS name,other.source_id AS source_id,
            count(DISTINCT p) AS paper_count ORDER BY paper_count DESC,id SKIP $skip LIMIT $limit""", params)
        items = [dict(row) for row in rows]
        # Only enumerate the selected anchor's neighbourhood, never every author pair.
        for item in items:
            item["identity_state"] = self._identity(item)
            papers = tx.run(pairs + """ AND other.id=$partner WITH DISTINCT p
                RETURN p.id AS id,p.name AS title,p.year AS year,p.source_id AS source_id,
                p.source_url AS source_url ORDER BY year DESC,id LIMIT $paper_limit""",
                dict(params, partner=item["id"], paper_limit=paper_limit))
            item["shared_papers"] = [dict(p) for p in papers]
            for paper in item["shared_papers"]:
                paper["sources"] = [{"source_id":paper["source_id"],"url":paper["source_url"]}] if paper["source_id"] or paper["source_url"] else []
            item["shared_papers_truncated"] = item["paper_count"] > paper_limit
        anchor_info=dict(id=anchor, name=exists["name"], source_id=exists["source_id"], paper_count=own_count)
        anchor_info["identity_state"]=self._identity(anchor_info)
        return dict(batch_id=batch, anchor=anchor_info,
                    items=items, total=total, page=page, page_size=page_size, shared_paper_limit=paper_limit,
                    truncated=total > page*page_size, filters=f,
                    basis="distinct stable paper IDs; joint authorship is not contribution or mentorship" if kind == "author"
                    else "same-paper evidenced author affiliations; institutional co-occurrence is not a contractual collaboration")

    def partners(self, anchor, batch_id, kind="author", filters=None, page=1, page_size=20, paper_limit=10):
        def operation(tx):
            batch = self.resolve(tx, batch_id)
            result = self._partners(tx, batch, anchor, kind, filters or {}, page, page_size, paper_limit)
            result["revision"] = tx.run("MATCH (b:CVBatch {id:$batch}) RETURN b.source_revision AS revision",batch=batch).single()["revision"]
            return result
        return self.run(operation)

    def report_statistics(self, batch_id, expected_revision=None, filters=None, limit=30,
                          author_id=None, institution_id=None):
        from .repository import GraphError
        f = normalize(filters or {})

        def operation(tx):
            batch = self.resolve(tx, batch_id)
            meta = self._summary_meta(tx, batch)
            revision = meta.get("source_revision")
            if expected_revision is not None and revision != expected_revision:
                raise GraphError(409, "REPORT_REVISION_MISMATCH", "指定发布批次与报告知识 revision 不一致")
            stats = self._statistics(tx, batch, f, limit)
            papers = [dict(row) for row in tx.run("MATCH (p:CVEntity) WHERE " + self.where(f) + """
                RETURN p.id AS id,p.source_id AS source_id,p.year AS year,p.abstract AS abstract,
                p.source_url AS source_url,p.effective_partition_json AS partition ORDER BY id""", dict(f, batch=batch))]
            # PaperInput is the source of the provider envelope's source IDs, not a guessed URL prefix.
            ids, missing = [], dict(year=0, abstract=0, source_url=0, source_paper_id=0, source_updated_at=0, citation_count=0)
            export_times = set()
            for paper in papers:
                raw = json.loads(paper["partition"])["input"] if paper["partition"] else {}
                sid = raw.get("openalex_id") or paper["source_id"]
                ids.append(sid or paper["id"])
                missing["source_paper_id"] += not bool(sid)
                missing["year"] += paper["year"] is None
                missing["abstract"] += not bool(paper["abstract"])
                missing["source_url"] += not bool(raw.get("source_url") or paper["source_url"])
                missing["source_updated_at"] += 1  # Not supplied by the current PaperInput contract.
                missing["citation_count"] += 1
            if meta.get("effective_json"):
                export_times.add(json.loads(meta["effective_json"])["generated_at"])
            authors = self._ranked_entities(tx, batch, f, "author", limit)
            institutions = self._ranked_entities(tx, batch, f, "institution", limit)
            authors["papers_without_relation"] = stats["paper_count"]-authors["papers_with_relation"]
            institutions["papers_without_evidence"] = stats["paper_count"]-institutions["papers_with_relation"]
            author_anchor = author_id or (authors["items"][0]["id"] if authors["items"] else None)
            institution_anchor = institution_id or (institutions["items"][0]["id"] if institutions["items"] else None)
            coauthors = self._partners(tx, batch, author_anchor, "author", f, 1, limit, 10) if author_anchor else {
                "status": "no_authors_in_scope", "items": [], "total": 0}
            collaboration = self._partners(tx, batch, institution_anchor, "institution", f, 1, limit, 10) if institution_anchor else {
                "status": "no_institutions_in_scope", "items": [], "total": 0}
            coauthors["selection"] = "explicit_anchor" if author_id else "highest_paper_count_then_stable_id"
            collaboration["selection"] = "explicit_anchor" if institution_id else "highest_paper_count_then_stable_id"
            data = dict(format_version="c-report-statistics/1", batch_id=batch, revision=revision,
                        statistics=stats, distributions=stats["distributions"], years=stats["years"],
                        authors=authors, institutions=institutions, coauthors=coauthors,
                        institution_collaborations=collaboration,
                        trends={"status": "definition_pending", "series": None,
                                "reason": "第四周正式需求尚未定义双序列含义、时间粒度和范围；不使用批次事件或分类代替"},
                        scope=dict(kind="filtered_published_snapshot" if f else "published_snapshot", filters=f,
                                   unit="distinct_papers", historical_accumulation=False, paper_count=stats["paper_count"]),
                        times=dict(knowledge_exported_at=sorted(export_times), graph_first_published_at=meta.get("published_at"),
                                   graph_last_activated_at=meta.get("last_activated_at"),
                                   source_updated_at=None, statistics_generated_at=datetime.now(timezone.utc).isoformat()),
                        coverage=dict(missing=missing, authors_without_relation=stats["paper_count"]-authors["papers_with_relation"],
                                      institutions_without_evidence=stats["paper_count"]-institutions["papers_with_relation"],
                                      notice="缺失与0不同；分类可多选；自动知识不等于人工确认；作者标签不表示专长"),
                        available_sections=["years", "distributions", "authors", "institutions", "coauthors", "institution_collaborations"],
                        pending_sections=["dual_trends"])
            return dict(provider="C", revision=revision, paper_ids=sorted(ids), data=data)
        return self.run(operation)
