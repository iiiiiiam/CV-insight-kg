"""Download a complete OpenAlex conference/year batch as a checked JSONL file."""

from __future__ import annotations

import argparse
import hashlib
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
ANNOTATION_FIELDS = "primary_topic,topics,keywords"

ANNOTATION_FIELDS = "primary_topic,topics,keywords"

def fetch_batch(venue: str, year: int, output: Path, retries: int = 5, *, with_annotations: bool = False) -> dict:
    if venue not in SOURCES:
        raise ValueError(f"No verified OpenAlex source for {venue}")
    if retries < 1 or not 1 <= page_size <= 100:
        raise ValueError("Invalid retries or page size")
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
        "select": FIELDS + ("," + ANNOTATION_FIELDS if with_annotations else ""),
    }
    if use_cursor:
        params["cursor"] = cursor
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    checkpoint = output.with_suffix(output.suffix + ".checkpoint.json")
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved.get("requested_fields", FIELDS.split(",")) != params["select"].split(","):
            raise ValueError("Download checkpoint fields changed; use a new output path")
        if (saved["venue"], saved["year"], saved["cursor_mode"], saved["page_size"]) != (venue, year, use_cursor, page_size):
            raise ValueError("Download checkpoint scope changed; use a new output path")
        if not partial.exists() and output.exists():
            complete = output.read_bytes()
            if saved['count'] == saved['expected'] and hashlib.sha256(complete).hexdigest() == saved['sha256']:
                partial.write_bytes(complete)
            else:
                raise ValueError('Download checkpoint has no matching partial file')
        body = partial.read_bytes()
        size = saved.get("size", len(body))
        if len(body) > size and hashlib.sha256(body[:size]).hexdigest() == saved["sha256"]:
            body = body[:size]
            partial.write_bytes(body)
        if hashlib.sha256(body).hexdigest() != saved["sha256"]:
            raise ValueError("Download checkpoint checksum mismatch")
        seen = {json.loads(line)["id"] for line in body.decode().splitlines()}
        count, expected, cursor, page = saved["count"], saved["expected"], saved["cursor"], saved["page"]
        if len(seen) != count:
            raise ValueError("Download checkpoint count mismatch")
    with partial.open("a" if checkpoint.exists() else "w", encoding="utf-8") as file:
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
                if work.get("publication_year") != year or source.get("id") != "https://openalex.org/" + source_id:
                    raise RuntimeError(f"Unexpected work in {venue} {year}: {identifier}")
                if identifier in seen:
                    raise RuntimeError(f"Duplicate work during pagination: {identifier}")
                seen.add(identifier)
                file.write(json.dumps(work, ensure_ascii=False) + "\n")
                count += 1
            file.flush()
            print(f"{venue} {year}: fetched {count}/{expected}", flush=True)
            next_cursor = batch['meta'].get('next_cursor')
            if use_cursor and count < expected and not next_cursor:
                raise RuntimeError('OpenAlex ended its cursor before the announced record count')
            cursor = next_cursor
            page += 1
            os.fsync(file.fileno())
            saved = {"requested_fields": params["select"].split(","), "venue": venue, "year": year, "cursor_mode": use_cursor, "page_size": page_size,
                     "count": count, "expected": expected, "cursor": cursor, "page": page, "size": partial.stat().st_size,
                     "sha256": hashlib.sha256(partial.read_bytes()).hexdigest()}
            temporary = checkpoint.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved), encoding="utf-8")
            temporary.replace(checkpoint)
            time.sleep(0.2)
    if not count or count != expected:
        raise RuntimeError(f"Incomplete batch: fetched {count}, expected {expected}")
    partial.replace(output)
    manifest = {"venue": venue, "year": year, "source": "openalex", "source_id": source_id,
                "count": count, "filter": params["filter"], "url": "https://api.openalex.org/works"}
    if with_annotations:
        manifest["requested_fields"] = params["select"].split(",")
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", choices=SOURCES)
    parser.add_argument("year", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--with-annotations", action="store_true", help="Also retain OpenAlex topics and keywords")
    args = parser.parse_args()
    print(json.dumps(fetch_batch(args.venue, args.year, args.output, with_annotations=args.with_annotations), ensure_ascii=False))
