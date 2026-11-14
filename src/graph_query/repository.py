"""All research reads pin one published batch inside one Neo4j transaction."""
import hashlib
import json
import re
from neo4j import GraphDatabase, unit_of_work

from .models import BatchInput


class GraphError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class GraphRepository:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(
            uri, auth=(user, password), max_transaction_retry_time=5
        )
        self.database = database

    def close(self):
        self.driver.close()

    def run(self, operation, *, write=False):
        with self.driver.session(database=self.database) as session:
            return (session.execute_write if write else session.execute_read)(
                unit_of_work(timeout=15)(operation)
            )

    def initialize(self):
        # Separate autocommit schema transactions, compatible with Community Edition.
        statements = [
            "CREATE CONSTRAINT cv_entity_key IF NOT EXISTS FOR (n:CVEntity) REQUIRE (n.batch_id,n.id) IS UNIQUE",
            "CREATE CONSTRAINT cv_batch_key IF NOT EXISTS FOR (n:CVBatch) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT cv_registry_key IF NOT EXISTS FOR (n:CVRegistry) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX cv_paper_year IF NOT EXISTS FOR (n:CVEntity) ON (n.batch_id,n.kind,n.year)",
            "CREATE INDEX cv_entity_name IF NOT EXISTS FOR (n:CVEntity) ON (n.batch_id,n.kind,n.name)",
        ]
        with self.driver.session(database=self.database) as session:
            for statement in statements:
                session.run(statement).consume()
            session.run(
                "MERGE (r:CVRegistry {id:'research'}) ON CREATE SET r.revision=0"
            ).consume()

    @staticmethod
    def lock(tx):
        # The dependent property update obtains a write lock until commit. Every
        # import/publish uses this gate, so publication cannot race import or CAS.
        tx.run(
            "MATCH (r:CVRegistry {id:'research'}) SET r.revision=r.revision+1 RETURN r.revision"
        ).consume()

    def ingest(self, batch: BatchInput):
        data, digest = batch.model_dump(mode="json"), batch.digest()

        def operation(tx):
            self.lock(tx)
            old = tx.run(
                "MATCH (b:CVBatch {id:$id}) RETURN properties(b) AS b",
                id=batch.batch_id,
            ).single()
            if old:
                if old["b"]["digest"] != digest:
                    raise GraphError(409, "BATCH_IMMUTABLE", "批次号已存在且内容不同，请使用新批次号")
                return dict(old["b"], replay=True)
            tx.run(
                'CREATE (b:CVBatch {id:$id, digest:$digest, status:"ready", source_batch_id:$source, schema_version:$schema, vocabulary_version:$vocab, provenance:$provenance, entity_count:$nodes, relation_count:$edges, created_at:toString(datetime())})',
                id=batch.batch_id,
                digest=digest,
                source=batch.source_batch_id,
                schema=batch.schema_version,
                vocab=batch.vocabulary_version,
                provenance=batch.provenance,
                nodes=len(batch.entities),
                edges=len(batch.relations),
            ).consume()
            tx.run(
                "UNWIND $nodes AS n CREATE (e:CVEntity) SET e=n, e.batch_id=$batch",
                nodes=data["entities"],
                batch=batch.batch_id,
            ).consume()
            links = []
            for r in data["relations"]:
                links.append(
                    dict(
                        r,
                        id=hashlib.sha256(
                            json.dumps([r["source"], r["kind"], r["target"]]).encode()
                        ).hexdigest(),
                        evidence_json=json.dumps(r["evidence"], ensure_ascii=False),
                        paper_ids=sorted({e["paper_id"] for e in r["evidence"]}),
                    )
                )
            tx.run(
                "UNWIND $links AS r MATCH (s:CVEntity {batch_id:$batch,id:r.source}), (t:CVEntity {batch_id:$batch,id:r.target}) CREATE (s)-[:CV_LINK {id:r.id, kind:r.kind, status:r.status, evidence_json:r.evidence_json, paper_ids:r.paper_ids, batch_id:$batch}]->(t)",
                links=links,
                batch=batch.batch_id,
            ).consume()
            return dict(
                tx.run(
                    "MATCH (b:CVBatch {id:$id}) RETURN properties(b) AS b",
                    id=batch.batch_id,
                ).single()["b"],
                replay=False,
            )

        return self.run(operation, write=True)

    def batch(self, batch_id):
        def operation(tx):
            row = tx.run(
                "MATCH (b:CVBatch {id:$id}) RETURN properties(b) AS b", id=batch_id
            ).single()
            if not row:
                raise GraphError(404, "BATCH_NOT_FOUND", "批次不存在")
            result = dict(row["b"])
            actual = tx.run(
                "MATCH (n:CVEntity {batch_id:$id}) OPTIONAL MATCH (n)-[r:CV_LINK]->() RETURN count(DISTINCT n) AS entities, count(r) AS relations",
                id=batch_id,
            ).single()
            result["checks"] = {
                "counts_match": actual["entities"] == result["entity_count"]
                and actual["relations"] == result["relation_count"],
                "nonempty": actual["entities"] > 0,
                "formal_knowledge": result["provenance"] == "reviewed_export",
            }
            result["publishable"] = all(result["checks"].values())
            result["active_batch_id"] = tx.run(
                "MATCH (r:CVRegistry {id:'research'}) RETURN r.active_batch_id AS id"
            ).single()["id"]
            return result

        return self.run(operation)

    def publish(self, batch_id, expected, allow_fixture=False):
        def operation(tx):
            self.lock(tx)
            active = tx.run(
                "MATCH (r:CVRegistry {id:'research'}) RETURN r.active_batch_id AS id"
            ).single()["id"]
            if active != expected:
                raise GraphError(409, "ACTIVE_BATCH_CHANGED", "已发布版本发生变化，请刷新后再发布")
            row = tx.run(
                "MATCH (b:CVBatch {id:$id}) RETURN properties(b) AS b", id=batch_id
            ).single()
            if not row:
                raise GraphError(404, "BATCH_NOT_FOUND", "批次不存在")
            b = row["b"]
            if b["provenance"] == "developer_fixture" and not allow_fixture:
                raise GraphError(409, "FIXTURE_REQUIRES_OPT_IN", "演示夹具必须显式允许发布")
            counts = tx.run(
                "MATCH (n:CVEntity {batch_id:$id}) OPTIONAL MATCH (n)-[r:CV_LINK]->() RETURN count(DISTINCT n) AS n,count(r) AS r",
                id=batch_id,
            ).single()
            if counts["n"] != b["entity_count"] or counts["r"] != b["relation_count"]:
                raise GraphError(409, "QUALITY_CHECK_FAILED", "批次完整性检查失败，保留旧版本")
            tx.run(
                "MATCH (r:CVRegistry {id:'research'}), (b:CVBatch {id:$id}) SET r.active_batch_id=$id, b.status='published', b.published_at=coalesce(b.published_at,toString(datetime()))",
                id=batch_id,
            ).consume()
            return {
                "batch_id": batch_id,
                "previous_batch_id": active,
                "status": "published",
            }

        return self.run(operation, write=True)

    @staticmethod
    def resolve(tx, requested=None):
        if requested:
            row = tx.run(
                "MATCH (b:CVBatch {id:$id,status:'published'}) RETURN b.id AS id",
                id=requested,
            ).single()
        else:
            row = tx.run(
                "MATCH (r:CVRegistry {id:'research'}) WHERE r.active_batch_id IS NOT NULL RETURN r.active_batch_id AS id"
            ).single()
        if not row:
            raise GraphError(404, "PUBLISHED_BATCH_NOT_FOUND", "尚无可读取的已发布批次")
        return row["id"]

    @staticmethod
    def node(n):
        result = dict(n)
        result["label"] = result["name"]
        result["type"] = result["kind"].title()
        if result["kind"] == "paper":
            result["title"] = result["name"]
        return result

    @staticmethod
    def edge(r, source, target):
        result = dict(r)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return dict(result, source=source, target=target, type=result["kind"])

    @staticmethod
    def where(filters):
        clauses = ["p.batch_id=$batch", "p.kind='paper'"]
        if filters.get("q"):
            clauses.append("toLower(p.name) CONTAINS toLower($q)")
        if filters.get("year") is not None:
            clauses.append("p.year=$year")
        for kind in (
            "topic",
            "method",
            "author",
            "institution",
            "task",
            "dataset",
            "venue",
        ):
            if filters.get(kind):
                if kind == "institution":
                    clauses.append(
                        "EXISTS { MATCH (p)-[:CV_LINK {kind:'has_author'}]->(:CVEntity)-[aff:CV_LINK {kind:'affiliated_with'}]->(f:CVEntity {batch_id:$batch,kind:'institution'}) WHERE (f.id=$institution OR f.name=$institution) AND p.id IN aff.paper_ids }"
                    )
                else:
                    clauses.append(
                        f"EXISTS {{ MATCH (p)-[:CV_LINK]->(f:CVEntity {{batch_id:$batch,kind:'{kind}'}}) WHERE f.id=${kind} OR f.name=${kind} }}"
                    )
        return " AND ".join(clauses)

    def papers(self, filters, batch_id=None, page=1, page_size=20, sort="year_desc"):
        def operation(tx):
            batch = self.resolve(tx, batch_id)
            params = dict(
                filters, batch=batch, skip=(page - 1) * page_size, limit=page_size
            )
            match = "MATCH (p:CVEntity) WHERE " + self.where(filters)
            total = tx.run(match + " RETURN count(p) AS total", params).single()[
                "total"
            ]
            order = {
                "year_desc": "p.year DESC,p.id",
                "year_asc": "p.year ASC,p.id",
                "title": "p.name,p.id",
            }[sort]
            rows = tx.run(
                match
                + f" RETURN properties(p) AS p ORDER BY {order} SKIP $skip LIMIT $limit",
                params,
            )
            return {
                "items": [self.node(r["p"]) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
                "batch_id": batch,
            }

        return self.run(operation)

    def entities(self, q="", kind=None, batch_id=None, limit=30):
        def operation(tx):
            batch = self.resolve(tx, batch_id)
            rows = tx.run(
                "MATCH (n:CVEntity {batch_id:$batch}) WHERE ($kind IS NULL OR n.kind=$kind) AND (toLower(n.name) CONTAINS toLower($q) OR n.id=$q) RETURN properties(n) AS n ORDER BY n.name,n.id LIMIT $limit",
                batch=batch,
                kind=kind,
                q=q,
                limit=limit + 1,
            )
            items = list(rows)
            return {
                "items": [self.node(row["n"]) for row in items[:limit]],
                "truncated": len(items) > limit,
                "batch_id": batch,
            }

        return self.run(operation)

    def detail(self, entity_id, batch_id=None, expected_kind=None):
        def operation(tx):
            batch = self.resolve(tx, batch_id)
            record = tx.run(
                "MATCH (n:CVEntity {batch_id:$batch,id:$id}) RETURN properties(n) AS n",
                batch=batch,
                id=entity_id,
            ).single()
            if not record or (expected_kind and record["n"]["kind"] != expected_kind):
                raise GraphError(404, "ENTITY_NOT_FOUND", "当前批次中不存在该实体")
            rows = tx.run(
                "MATCH (n:CVEntity {batch_id:$batch,id:$id})-[r:CV_LINK]-(m:CVEntity {batch_id:$batch}) RETURN properties(m) AS n,properties(r) AS r,startNode(r).id AS source,endNode(r).id AS target ORDER BY r.id LIMIT 201",
                batch=batch,
                id=entity_id,
            )
            values = list(rows)
            return {
                "node": self.node(record["n"]),
                "related": [self.node(r["n"]) for r in values[:200]],
                "relations": [
                    self.edge(r["r"], r["source"], r["target"]) for r in values[:200]
                ],
                "truncated": len(values) > 200,
                "batch_id": batch,
            }

        return self.run(operation)

    def graph(self, seed, hops=1, batch_id=None, limit=100, types=None, filters=None):
        def operation(tx):
            batch = self.resolve(tx, batch_id)
            params = dict(
                filters or {},
                batch=batch,
                seed=seed,
                limit=limit + 1,
                types=types or [],
            )
            exists = tx.run(
                "MATCH (n:CVEntity {batch_id:$batch,id:$seed}) RETURN properties(n) AS n",
                params,
            ).single()
            if not exists:
                raise GraphError(404, "ENTITY_NOT_FOUND", "起点不在当前已发布批次中")
            # All paths remain in the pinned batch. Filter every paper in a path
            # so year/topic/method constraints cannot leak unrelated papers.
            condition = re.sub(r"\bp\b", "paper", self.where(filters or {}))
            rows = list(
                tx.run(
                    f"""MATCH path=(s:CVEntity {{batch_id:$batch,id:$seed}})-[:CV_LINK*1..{hops}]-(n:CVEntity)
                WHERE all(v IN nodes(path) WHERE v.batch_id=$batch)
                AND all(r IN relationships(path) WHERE size($types)=0 OR r.kind IN $types)
                AND all(paper IN [v IN nodes(path) WHERE v.kind='paper'] WHERE {condition})
                RETURN path LIMIT $limit""",
                    params,
                )
            )
            nodes = {seed: self.node(exists["n"])}
            edges = {}
            for row in rows[:limit]:
                for n in row["path"].nodes:
                    nodes[n["id"]] = self.node(n)
                for r in row["path"].relationships:
                    edges[r["id"]] = self.edge(r, r.start_node["id"], r.end_node["id"])
            return {
                "nodes": list(nodes.values()),
                "edges": list(edges.values()),
                "batch_id": batch,
                "truncated": len(rows) > limit,
                "limit_unit": "paths",
                "seed": seed,
                "hops": hops,
            }

        return self.run(operation)
