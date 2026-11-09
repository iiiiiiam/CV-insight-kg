import json
from .effective import project, canonical


class EffectiveStore:
    def ingest_effective(self, document):
        from .repository import GraphError

        nodes, edges = project(document)
        bid = "effective-" + document["revision"]

        def operation(tx):
            self.lock(tx)
            old = tx.run(
                "MATCH (b:CVBatch {id:$id}) RETURN properties(b) AS b", id=bid
            ).single()
            if old:
                self._check_effective(tx, old["b"])
                result = dict(old["b"])
                result.pop("effective_json", None)
                return dict(result, replay=True)
            props = dict(
                id=bid,
                digest=document["revision"],
                source_revision=document["revision"],
                status="ready",
                provenance="effective_export",
                source_batch_id="B-effective:" + document["revision"],
                schema_version="knowledge-effective/1.0",
                vocabulary_version="per-paper",
                entity_count=len(nodes),
                relation_count=len(edges),
                paper_count=document["counts"]["papers"],
                source_entity_count=document["counts"]["entities"],
                review_state_counts_json=canonical(document["counts"]["review_states"]),
                effective_json=canonical(document),
            )
            tx.run("CREATE (b:CVBatch) SET b=$props", props=props).consume()
            tx.run(
                "UNWIND $nodes AS n CREATE (e:CVEntity) SET e=n,e.batch_id=$batch",
                nodes=nodes,
                batch=bid,
            ).consume()
            tx.run(
                "UNWIND $edges AS e MATCH (s:CVEntity {batch_id:$batch,id:e.source}),(t:CVEntity {batch_id:$batch,id:e.target}) CREATE (s)-[r:CV_LINK]->(t) SET r=e,r.batch_id=$batch",
                edges=edges,
                batch=bid,
            ).consume()
            self._check_effective(tx, props)
            props.pop("effective_json")
            return dict(props, replay=False)

        return self.run(operation, write=True)

    @staticmethod
    def _check_effective(tx, props):
        from .repository import GraphError

        if not props.get("effective_json"):
            return
        nodes, edges = project(json.loads(props["effective_json"]))
        batch = props["id"]
        an = {
            r["n"]["id"]: dict(r["n"])
            for r in tx.run(
                "MATCH (n:CVEntity {batch_id:$batch}) RETURN properties(n) AS n",
                batch=batch,
            )
        }
        en = {
            n["id"]: {k: v for k, v in dict(n, batch_id=batch).items() if v is not None}
            for n in nodes
        }
        ae = {
            r["r"]["id"]: dict(r["r"], source=r["source"], target=r["target"])
            for r in tx.run(
                "MATCH (:CVEntity {batch_id:$batch})-[r:CV_LINK]->(:CVEntity {batch_id:$batch}) RETURN properties(r) AS r,startNode(r).id AS source,endNode(r).id AS target",
                batch=batch,
            )
        }
        ee = {e["id"]: dict(e, batch_id=batch) for e in edges}
        if an != en or ae != ee:
            raise GraphError(409, "QUALITY_CHECK_FAILED", "快照内容、证据或版本不完整，未发布")
