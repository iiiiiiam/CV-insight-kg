"""D's selected publication policy, independent of C storage implementation."""


class GraphBoundaryError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


PUBLIC_PROVENANCE = {"reviewed_export", "effective_export"}


def require_reviewed_batch(metadata, batch_id, *, published=False):
    """Validate a C batch that may be read by the public research workspace.

    The historic name remains because older D callers and tests use it.  A B
    effective export is now the normal public source: it contains automatic
    extraction results plus public corrections, and must not be relabelled as
    a manually reviewed export.
    """
    if not isinstance(metadata, dict) or metadata.get('id', metadata.get('batch_id')) != batch_id:
        raise GraphBoundaryError(502, 'C_CONTRACT_INVALID', 'C 返回的批次信息与请求不一致。')
    if metadata.get('provenance') not in PUBLIC_PROVENANCE:
        raise GraphBoundaryError(409, 'PUBLIC_KNOWLEDGE_REQUIRED', '研究端只展示 B 的公共知识快照；开发夹具不能用于当前研究页面。')
    if published and metadata.get('status') != 'published':
        raise GraphBoundaryError(409, 'PUBLISHED_DATA_REQUIRED', '该批次尚未发布，请先完成校验和发布。')
    return metadata
