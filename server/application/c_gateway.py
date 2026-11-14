"""HTTP integration only: C remains responsible for Neo4j queries and writes."""

from urllib.parse import quote
import httpx

from server.application.graph_policy import GraphBoundaryError, require_reviewed_batch


class CServiceClient:
    def __init__(self, settings):
        self.settings = settings

    async def request(self, method, path, *, params=None, body=None):
        if path.startswith('/api/admin/') and not self.settings.c_admin_token:
            raise GraphBoundaryError(503, 'C_ADMIN_NOT_CONFIGURED', '请先配置 D 的 C_ADMIN_TOKEN，并与 C 服务的 GRAPH_ADMIN_TOKEN 保持一致。')
        headers = {'Accept': 'application/json'}
        if self.settings.c_admin_token:
            headers['Authorization'] = 'Bearer ' + self.settings.c_admin_token
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.request(method, self.settings.c_base_url + path,
                                                params=params, json=body, headers=headers)
        except httpx.RequestError as exc:
            raise GraphBoundaryError(503, 'C_SERVICE_UNAVAILABLE', '无法连接 C 图谱服务，请检查 8002 服务及 Neo4j；不会回退到其他数据。') from exc
        if response.status_code == 401:
            raise GraphBoundaryError(503, 'C_SERVICE_CREDENTIALS_INVALID', 'C 服务凭据不匹配，请检查服务端配置；这不代表 D 登录过期。')
        return response

    async def batch(self, batch_id):
        response = await self.request('GET', '/api/admin/batches/' + quote(batch_id, safe=''))
        return response

    async def research(self, path, params):
        response = await self.request('GET', path, params=params)
        if not response.is_success:
            return response
        try:
            payload = response.json()
            batch_id = payload['batch_id']
            if not isinstance(batch_id, str) or not batch_id:
                raise ValueError('batch_id')
        except (ValueError, KeyError, TypeError) as exc:
            raise GraphBoundaryError(502, 'C_CONTRACT_INVALID', 'C 研究响应缺少有效批次标识。') from exc
        metadata_response = await self.batch(batch_id)
        if not metadata_response.is_success:
            return metadata_response
        try:
            metadata = require_reviewed_batch(metadata_response.json(), batch_id, published=True)
            if not isinstance(metadata.get('source_batch_id'), str):
                raise ValueError('source_batch_id')
        except (ValueError, TypeError) as exc:
            raise GraphBoundaryError(502, 'C_CONTRACT_INVALID', 'C 批次元数据格式不正确。') from exc
        # Preserve C's original IDs and evidence arrays. Never relabel developer fixtures.
        return httpx.Response(response.status_code, json={**payload,
            'batch_provenance': metadata['provenance'], 'source_batch_id': metadata['source_batch_id']})
