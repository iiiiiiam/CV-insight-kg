"""Convert the complete, validated B confirmed export with C's existing adapter."""

from server.application.graph_policy import GraphBoundaryError
from server.application.knowledge import KnowledgeSnapshotChanged
from src.knowledge_builder.export import build_exports


def prepare_graph_batch(snapshot, batch_id, source_batch_id, snapshot_revision):
    if snapshot_revision != snapshot.snapshot_revision:
        raise KnowledgeSnapshotChanged('B 审核结果已变化，请重新读取并生成批次预览。')
    # Import only when preparing a batch; basic A/B reads do not depend on C startup.
    from src.graph_query.b_adapter import adapt_confirmed
    try:
        bundle = build_exports(snapshot.papers, list(snapshot.results.values()), snapshot.sessions)
        confirmed = bundle['confirmed']
        if not confirmed['papers']:
            raise GraphBoundaryError(422, 'NO_CONFIRMED_KNOWLEDGE', 'B 尚无已确认知识，请先人工审核；不会使用开发夹具补足。')
        batch = adapt_confirmed(confirmed, batch_id, source_batch_id)
    except GraphBoundaryError:
        raise
    except ValueError as exc:
        raise GraphBoundaryError(422, 'B_TO_C_VALIDATION_FAILED',
            '无法生成 C 批次：请检查每个已确认分区是否包含论文实体、名称是否一致及证据是否有效。' + str(exc)[:1000]) from exc
    payload = batch.model_dump(mode='json')
    return payload, {'batch_id': batch.batch_id, 'source_batch_id': batch.source_batch_id,
        'snapshot_revision': snapshot.snapshot_revision, 'digest': batch.digest(),
        'provenance': batch.provenance, 'entity_count': len(batch.entities),
        'relation_count': len(batch.relations), 'paper_count': sum(n.kind == 'paper' for n in batch.entities),
        'schema_version': batch.schema_version, 'vocabulary_version': batch.vocabulary_version}
