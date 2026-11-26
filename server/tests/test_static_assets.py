"""Windows MIME associations must not turn the packaged frontend into a blank page."""
import mimetypes
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from server.api.main import create_app
from server.configuration.settings import Settings


def test_module_asset_has_javascript_mime_even_when_registry_says_plain_text(tmp_path, monkeypatch):
    index=Path(__file__).resolve().parents[2]/'frontend/dist/index.html'
    if not index.exists():
        pytest.skip('Build frontend before verifying served module assets')
    asset=re.search(r'<script[^>]+src="([^"]+)"',index.read_text(encoding='utf-8')).group(1)
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map,'.js','text/plain')
    assert mimetypes.guess_type('test.js')[0]=='text/plain'
    settings=Settings(username='mime-test',password='offline-password-123',secret='s'*48,
                      user_store=str(tmp_path/'users.json'),auto_graph_sync=False)
    with TestClient(create_app(settings)) as client:
        response=client.get(asset)
        assert response.status_code==200
        assert response.headers['content-type'].split(';')[0]=='text/javascript'
        assert response.headers['x-content-type-options']=='nosniff'
        assert len(response.content)>0
