"""Download a complete OpenAlex conference/year batch as a checked JSONL file."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests

SOURCES = {
    "CVPR": "S4210176548",
    "ICCV": "S4363607764",
}
FIELDS = "id,display_name,publication_year,doi,authorships,abstract_inverted_index,cited_by_count,primary_location,type"


def fetch_batch(venue: str, year: int, output: Path, retries: int = 5) -> dict:
    if venue not in SOURCES:
        raise ValueError(f"No verified OpenAlex source for {venue}")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    source_id = SOURCES[venue]
    cursor = "*"
    page = 1
    use_cursor = bool(os.getenv("OPENALEX_API_KEY"))
    expected = None
    count = 0
    seen = set()
    session = requests.Session()
    params = {
        "filter": f"primary_location.source.id:{source_id},publication_year:{year}",
        "per_page": 100,
        "select": FIELDS,
    }
    if use_cursor:
        params["cursor"] = cursor
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    with partial.open("w", encoding="utf-8") as file:
        while cursor if use_cursor else (expected is None or count < expected):
            if use_cursor:
                params["cursor"] = cursor
            else:
                params["page"] = page
            for attempt in range(retries):
                try:
                    response = session.get("https://api.openalex.org/works", params=params, timeout=60)
                    if response.status_code in (429, 500, 502, 503, 504):
                        delay = min(int(response.headers.get("Retry-After", "0") or 0) or 2 ** attempt, 60)
                        time.sleep(delay)
                        continue
                    response.raise_for_status()
                    batch = response.json()
                    break
                except (requests.RequestException, ValueError):
                    if attempt + 1 == retries:
                        raise
                    time.sleep(min(2 ** attempt, 30))
            else:
                raise RuntimeError(f"OpenAlex request failed after {retries} attempts")
            expected = batch["meta"]["count"] if expected is None else expected
            if not use_cursor and expected > 10000:
                raise RuntimeError("Basic paging is limited to 10,000 records; set OPENALEX_API_KEY")
            if batch["meta"]["count"] != expected:
                raise RuntimeError("OpenAlex result count changed during pagination; retry the batch")
            results = batch["results"]
            if not results:
                break
            for work in results:
                identifier = work["id"]
                location = work.get("primary_location") or {}
                source = location.get("source") or {}
                if work.get("publication_year") != year or not source.get("id", "").endswith(source_id):
                    raise RuntimeError(f"Unexpected work in {venue} {year}: {identifier}")
                if identifier in seen:
                    raise RuntimeError(f"Duplicate work during pagination: {identifier}")
                seen.add(identifier)
                file.write(json.dumps(work, ensure_ascii=False) + "\n")
                count += 1
            file.flush()
            print(f"{venue} {year}: fetched {count}/{expected}", flush=True)
            cursor = batch["meta"].get("next_cursor")
            page += 1
            time.sleep(0.2)
    if not count or count != expected:
        raise RuntimeError(f"Incomplete batch: fetched {count}, expected {expected}")
    partial.replace(output)
    manifest = {"venue": venue, "year": year, "source": "openalex", "source_id": source_id,
                "count": count, "filter": params["filter"], "url": "https://api.openalex.org/works"}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", choices=SOURCES)
    parser.add_argument("year", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(fetch_batch(args.venue, args.year, args.output), ensure_ascii=False))
