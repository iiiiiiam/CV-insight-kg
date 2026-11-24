"""Replaceable sources; authentication belongs to the injected server-side client."""
import json
from pathlib import Path
from .effective import validate_effective


class FileEffectiveSource:
    def __init__(self, path):
        self.path = Path(path)

    def load(self, expected_revision=None):
        doc = validate_effective(json.loads(self.path.read_text(encoding="utf-8")))
        if expected_revision and doc["revision"] != expected_revision:
            raise ValueError("Effective revision changed")
        return doc


class HttpEffectiveSource:
    """Client must have the trusted B base URL and a valid administrator cookie.

    No browser cookie extraction, persistent credential storage, or login retries.
    B presently has no machine authentication; this is an opt-in transport seam.
    """

    def __init__(self, authenticated_client):
        from urllib.parse import urlparse

        url = urlparse(str(authenticated_client.base_url))
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("Use HTTPS or trusted loopback B service")
        self.client = authenticated_client

    def load(self, expected_revision=None):
        params = {"expected_revision": expected_revision} if expected_revision else {}
        response = self.client.get(
            "/api/admin/knowledge/effective-export",
            params=params,
            follow_redirects=False,
            timeout=60,
        )
        if response.status_code != 200:
            raise ValueError(f"B effective export failed: HTTP {response.status_code}")
        doc = validate_effective(response.json())
        if response.headers.get("X-Knowledge-Revision") != doc["revision"]:
            raise ValueError("B revision header mismatch")
        if expected_revision and doc["revision"] != expected_revision:
            raise ValueError("Effective revision changed")
        return doc
