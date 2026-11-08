import httpx

from server.configuration.settings import Settings


class AServiceUnavailable(RuntimeError):
    pass


class AServiceClient:
    """D 到 A 的唯一出口；A 的管理员令牌不会进入浏览器。"""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def request(self, method: str, path: str, *, params=None, body=None) -> httpx.Response:
        headers = {'Accept': 'application/json'}
        if self.settings.a_admin_token:
            headers['Authorization'] = f'Bearer {self.settings.a_admin_token}'
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                return await client.request(
                    method,
                    f'{self.settings.a_base_url}{path}',
                    params=params,
                    json=body,
                    headers=headers,
                )
        except httpx.RequestError as exc:
            raise AServiceUnavailable(f'无法连接 A 数据服务：{exc.__class__.__name__}') from exc
