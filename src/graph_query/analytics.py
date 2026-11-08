"""Published-snapshot statistics. Counts are distinct papers, never evidence hits."""





import json

class GraphAnalytics:

    def _statistics(self, tx, batch, filters, limit):

        params = dict(filters, batch=batch, limit=limit + 1)

        scope = "MATCH (p:CVEntity) WHERE " + self.where(filters)

        total = tx.run(scope + " RETURN count(DISTINCT p) AS n", params).single()["n"]

        years = [

            dict(row)

            for row in tx.run(

                scope

                + """ RETURN p.year AS year,

            count(DISTINCT p) AS paper_count ORDER BY year""",

                params,

            )

        ]

        distributions = {}

        for kind in ("topic", "method"):

            match = (

                scope

                + f""" MATCH (p)-[r:CV_LINK {{kind:'mentions_{kind}'}}]->

                (term:CVEntity {{batch_id:$batch,kind:'{kind}'}})"""

            )

            covered = tx.run(match + " RETURN count(DISTINCT p) AS n", params).single()[

                "n"

            ]

            rows = list(

                tx.run(

                    match

                    + """ RETURN term.id AS id, term.name AS name,

                count(DISTINCT p) AS paper_count ORDER BY paper_count DESC,id LIMIT $limit""",

                    params,

                )

            )

            distributions[kind] = {

                "items": [

                    dict(row, share=row["paper_count"] / total if total else 0)

                    for row in rows[:limit]

                ],

                "truncated": len(rows) > limit,

                "papers_with_effective_relation": covered,
                "papers_with_confirmed_relation": covered,

                "papers_without_effective_relation": total-covered,
                "papers_without_confirmed_relation": total - covered,

            }

        meta = tx.run(

            "MATCH (b:CVBatch {id:$batch}) RETURN properties(b) AS b", batch=batch

        ).single()["b"]

        if meta["provenance"]=="effective_export":
            for d in distributions.values():
                d["papers_with_confirmed_relation"]=None
                d["papers_without_confirmed_relation"]=None
        return {

            "batch_id": batch,
            "review_state_counts": json.loads(meta.get("review_state_counts_json","null")),

            "provenance": meta["provenance"],

            "schema_version": meta["schema_version"],

            "vocabulary_version": meta["vocabulary_version"],

            "source_batch_id": meta["source_batch_id"],

            "filters": filters,

            "paper_count": total,

            "years": years,

            "distributions": distributions,

            "basis": {

                "unit": "distinct_papers",

                "denominator": "all_matching_papers_in_published_batch",

                "relations": "public_effective" if meta["provenance"]=="effective_export" else "confirmed_only",

                "multi_label": True,

                "notice": "同篇论文可计入多个主题/方法，占比之和可超过 100%；提及不等于使用。缺少有效关联不代表没有该研究内容。",

                "fixture": meta["provenance"] == "developer_fixture",

            },

        }



    def statistics(self, filters, batch_id, limit=30):

        def operation(tx):

            batch = self.resolve(tx, batch_id)

            return self._statistics(tx, batch, filters, limit)



        return self.run(operation)



    def author_profile(self, author_id, batch_id, page=1, page_size=20, limit=30):

        from .repository import GraphError



        def operation(tx):

            batch = self.resolve(tx, batch_id)

            row = tx.run(

                "MATCH (a:CVEntity {batch_id:$batch,id:$id,kind:'author'}) RETURN properties(a) AS a",

                batch=batch,

                id=author_id,

            ).single()

            if not row:

                raise GraphError(404, "AUTHOR_NOT_FOUND", "当前已发布批次中不存在该作者，请使用稳定 ID 查询")

            author = self.node(row["a"])

            same = tx.run(

                "MATCH (a:CVEntity {batch_id:$batch,kind:'author',name:$name}) WHERE a.id<>$id RETURN count(a) AS n",

                batch=batch,

                name=author["name"],

                id=author_id,

            ).single()["n"]

            stats = self._statistics(tx, batch, {"author_id": author_id}, limit)

            params = dict(

                batch=batch,

                author=author_id,

                author_id=author_id,

                skip=(page - 1) * page_size,

                limit=page_size,

            )

            rows = tx.run(

                "MATCH (p:CVEntity) WHERE "

                + self.where({"author_id": author_id})

                + """ RETURN properties(p) AS p

                ORDER BY p.year DESC,p.id SKIP $skip LIMIT $limit""",

                params,

            )

            papers = [self.node(row["p"]) for row in rows]

            institutions = [

                dict(row)

                for row in tx.run(

                    """MATCH (p:CVEntity {batch_id:$batch,kind:'paper'})

                -[:CV_LINK {kind:'has_author'}]->(a:CVEntity {batch_id:$batch,id:$author})

                -[aff:CV_LINK {kind:'affiliated_with'}]->(i:CVEntity {batch_id:$batch,kind:'institution'})

                WHERE p.id IN aff.paper_ids RETURN i.id AS id,i.name AS name,collect(DISTINCT p.id) AS paper_ids ORDER BY id""",

                    params,

                )

            ]

            return {

                "batch_id": batch,

                "author": author,

                "statistics": stats,

                "papers": {

                    "items": papers,

                    "total": stats["paper_count"],

                    "page": page,

                    "page_size": page_size,

                },

                "institutions": institutions,

                "institution_status": "evidenced" if institutions else "not_confirmed",

                "identity": {

                    "key": "stable_entity_id",

                    "same_name_other_ids": same,

                    "merged_by_name": False,

                },

            }



        return self.run(operation)
