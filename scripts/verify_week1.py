"""Verify A's week-one delivery through a running API, without external data requests."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values


def verify(base_url: str, token: str | None, baseline: dict) -> dict:
    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": "Bearer " + token} if token else {}
    body = {"dataset_id": baseline["dataset_id"]}

    def request(method, path, authenticated=True, **kwargs):
        response = session.request(method, base_url.rstrip("/") + path,
                                   headers=headers if authenticated else {}, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    local_demo = request("GET", "/api/runtime", authenticated=False)["local_demo"]
    anonymous_status = invalid_status = None
    if not local_demo:
        if not token:
            raise RuntimeError("This server requires administrator authentication")
        anonymous = session.post(base_url.rstrip("/") + "/api/admin/imports", json=body, timeout=30)
        invalid = session.post(base_url.rstrip("/") + "/api/admin/imports", json=body,
                               headers={"Authorization": "Bearer invalid-verification-token"}, timeout=30)
        anonymous_status, invalid_status = anonymous.status_code, invalid.status_code
        if anonymous_status != 401 or invalid_status != 403:
            raise RuntimeError("Sample import authorization checks failed")
    announced = request("GET", "/api/admin/datasets")["items"][0]
    if announced["dataset_id"] != baseline["dataset_id"] or announced["sha256"] != baseline["sha256"]:
        raise RuntimeError("Server dataset differs from the handoff baseline")
    before = request("GET", "/api/papers?page_size=1")["total"]
    batches, totals, identifiers = [], [], []
    expected_ids = {paper["openalex_id"] for paper in baseline["papers"]}
    for _ in range(2):
        job = request("POST", "/api/admin/imports", json=body)
        if job["status"] != "succeeded" or job["succeeded"] != 20 or job["failed"] or job["paper_count"] != 20:
            raise RuntimeError("The 20-paper sample import did not succeed")
        papers = request("GET", f"/api/admin/jobs/{job['id']}/papers?page_size=100")["items"]
        if {paper["openalex_id"] for paper in papers} != expected_ids:
            raise RuntimeError("Imported papers differ from the fixed baseline")
        if not all(paper["title"] and paper["year"] == 2024 and paper["source_url"]
                   and job["id"] in paper["batch_ids"] for paper in papers):
            raise RuntimeError("Missing paper metadata or batch linkage")
        detail = request("GET", f"/api/papers/{papers[0]['id']}")
        if not detail["sources"] or not detail["sources"][0]["retrieved_at"]:
            raise RuntimeError("Paper provenance is missing")
        batches.append(job["batch_id"])
        totals.append(job["total_papers"])
        identifiers.append({paper["openalex_id"]: paper["id"] for paper in papers})
    if totals[0] != totals[1] or identifiers[0] != identifiers[1] or batches[0] == batches[1]:
        raise RuntimeError("Rerun changed paper IDs/counts or failed to record a new batch")
    return {"verified_at": datetime.now(timezone.utc).isoformat(), "verification_type": "automated",
            "dataset_id": baseline["dataset_id"], "source": baseline["source"], "venue": baseline["venue"],
            "year": baseline["year"], "baseline_sha256": baseline["sha256"], "expected_count": 20,
            "access_mode": "local_demo" if local_demo else "protected",
            "anonymous_import_status": anonymous_status, "invalid_token_status": invalid_status,
            "total_before": before, "total_after_first": totals[0], "total_after_second": totals[1],
            "batch_ids": batches, "linked_papers_per_batch": [20, 20], "stable_paper_ids": True,
            "non_owner_manual_acceptance": "pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    token = os.getenv("ADMIN_TOKEN") or dotenv_values(root / ".env").get("ADMIN_TOKEN")
    baseline = json.loads((root / "examples" / "week1_baseline.json").read_text(encoding="utf-8"))
    report = verify(args.url, token, baseline)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
