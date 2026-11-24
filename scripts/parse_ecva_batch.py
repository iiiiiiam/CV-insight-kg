"""Extract the ECCV 2024 main-conference metadata from ECVA's official index."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://www.ecva.net/"


def parse_index(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    button = next((b for b in soup.select("button.accordion") if b.get_text(" ", strip=True) == "ECCV 2024 Papers"), None)
    if button is None:
        raise ValueError("ECCV 2024 section not found")
    section = button.find_next_sibling("div", class_="accordion-content")
    if section is None:
        raise ValueError("ECCV 2024 records not found")
    rows = []
    for title_node in section.select("dt.ptitle"):
        link = title_node.find("a", href=True)
        match = re.search(r"/([0-9]+)_ECCV_2024_paper\.php$", link["href"] if link else "")
        authors_node = title_node.find_next_sibling("dd")
        links_node = authors_node.find_next_sibling("dd") if authors_node else None
        doi_link = links_node.select_one('a[href*="link.springer.com/chapter/"]') if links_node else None
        if not match or not doi_link:
            raise ValueError("Incomplete ECCV 2024 paper record")
        doi = doi_link["href"].split("/chapter/", 1)[1].split("?", 1)[0].lower()
        rows.append({
            "source_id": f"eccv2024:{match.group(1)}",
            "source_url": urljoin(BASE, link["href"]),
            "title": link.get_text(" ", strip=True),
            "year": 2024,
            "venue": "ECCV",
            "doi": doi,
            "authors": [x.strip().rstrip("*").strip() for x in authors_node.get_text(" ", strip=True).split(",") if x.strip()],
            "raw": {"index_url": BASE + "papers.php", "paper_url": urljoin(BASE, link["href"]),
                    "doi_url": doi_link["href"], "title_html": str(title_node),
                    "authors_html": str(authors_node)},
        })
    ids = [r["source_id"] for r in rows]
    if not rows or len(set(ids)) != len(ids):
        raise ValueError("Empty or duplicate ECVA paper IDs")
    duplicates = {doi for doi, count in Counter(r["doi"] for r in rows).items() if count > 1}
    for row in rows:
        if row["doi"] in duplicates:
            row["raw"]["doi_note"] = "Duplicate DOI in ECVA index; needs manual verification"
            row["doi"] = None
    return rows


def write_batch(source: Path, output: Path) -> dict:
    rows = parse_index(source.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {"venue": "ECCV", "year": 2024, "source": "ecva", "count": len(rows),
                "url": BASE + "papers.php", "ambiguous_doi_rows": sum(r["doi"] is None for r in rows)}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_batch(args.source, args.output), ensure_ascii=False))
