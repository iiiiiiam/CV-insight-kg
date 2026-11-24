"""Read-only, cached source probes. No database, review writes, or UI dependency."""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .extraction import fingerprint

OPENALEX_FIELDS = "id,display_name,publication_year,primary_topic,topics,keywords,ids,locations,best_oa_location"


class SourceUnavailable(ValueError):
    pass


def normalized(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def same_paper(paper, record):
    """Conservative match: exact normalized title + a full author name + nearby year."""
    if normalized(paper.title) != normalized(record.get("title") or ""):
        return False
    authors = {normalized((a.get("author") or {}).get("display_name") or "") for a in paper.authorships}
    others = {normalized(a) for a in (record.get("authors") or []) if isinstance(a, str)}
    published = str(record.get("published") or "")[:4]
    return bool((authors - {""}) & others) and published.isdigit() and abs(int(published) - paper.year) <= 2


class SourceClient:
    def __init__(self, cache_directory, *, session=None, timeout=15, refresh=False, offline=False):
        self.cache = Path(cache_directory)
        self.session = session or requests.Session()
        self.timeout = timeout
        self.refresh = refresh
        self.offline = offline
        self.requests = 0
        self.cache_hits = 0

    def read(self, source, url, params=None):
        public_params = dict(params or {})
        key = fingerprint([url, public_params])
        path = self.cache / source / (key + ".json")
        if path.exists() and not self.refresh:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["digest"] != fingerprint(record["payload"]):
                    raise ValueError("checksum")
                if record["url"] != url or record["params"] != public_params or record["source"] != source:
                    raise ValueError("request identity")
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceUnavailable("Source cache is invalid; keep it and rerun with --refresh") from exc
            self.cache_hits += 1
            return record
        if self.offline:
            raise SourceUnavailable("Source is not cached; offline mode does not make requests")
        request_params = dict(public_params)
        if source == "openalex" and os.getenv("OPENALEX_API_KEY"):
            request_params["api_key"] = os.environ["OPENALEX_API_KEY"]
        for attempt in range(2):
            try:
                self.requests += 1
                response = self.session.get(url, params=request_params, timeout=self.timeout)
                if response.status_code in (429, 500, 502, 503, 504) and not attempt:
                    time.sleep(1)
                    continue
                if not response.ok:
                    raise SourceUnavailable(f"{source} HTTP {response.status_code}")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                break
            except (requests.RequestException, ValueError) as exc:
                if isinstance(exc, SourceUnavailable):
                    raise
                # Never include exception URLs: a query can contain a credential.
                raise SourceUnavailable(f"{source} request failed ({type(exc).__name__})") from None
        record = dict(source=source, url=url, params=public_params,
                      fetched_at=datetime.now(timezone.utc).isoformat(), payload=payload, digest=fingerprint(payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(record, file, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        time.sleep(.15)
        return record

    def openalex(self, paper):
        match = re.fullmatch(r"https://openalex.org/(W\d+)", paper.openalex_id)
        if not match:
            raise SourceUnavailable("Invalid OpenAlex work identifier")
        record = self.read("openalex", "https://api.openalex.org/works/" + match[1], {"select": OPENALEX_FIELDS})
        data = record["payload"]
        if (data.get("id") != paper.openalex_id
            or normalized(data.get("display_name") or "") != normalized(paper.title)
            or data.get("publication_year") != paper.year):
            raise SourceUnavailable("OpenAlex identity differs from the frozen input")
        return record

    def papers_with_code(self, paper):
        query = paper.title[:300]
        search = self.read("paperswithcode", "https://paperswithcode.co/api/v1/papers/search",
                           {"q": query, "mode": "keyword", "page_size": 5})
        results = search["payload"].get("results")
        if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
            raise SourceUnavailable("Catalog search schema changed")
        candidates = [r for r in results if same_paper(paper, r)]
        if len(candidates) != 1:
            raise SourceUnavailable("Papers with Code has no unique title/author/year match")
        candidate = candidates[0]
        identifier = str(candidate.get("arxiv_id") or candidate.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9.\-/]+", identifier) or ".." in identifier:
            raise SourceUnavailable("Invalid catalog identifier")
        # Modern identifiers are enough for the current conference pool.
        if "/" in identifier:
            raise SourceUnavailable("Legacy arXiv identifier is not supported by this probe")
        record = self.read("paperswithcode", "https://paperswithcode.co/api/v1/papers/" + identifier)
        if not same_paper(paper, record["payload"]):
            raise SourceUnavailable("Catalog detail identity differs from the frozen input")
        return record
