"""Isolated B HTTP acceptance using real A files. No team database or C publication."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import httpx
import uvicorn

from server.api.main import create_app
from server.configuration.settings import Settings
from src.graph_query.effective import validate_effective
from src.knowledge_builder.report_knowledge import validate_report_knowledge

ROOT = Path(__file__).resolve().parents[2]


def verify(output_directory=None):
    """Bind only loopback on an OS-selected port; always stop this server on exit."""
    if output_directory is not None:
        output_directory = Path(output_directory)
        if output_directory.exists():
            raise ValueError("Choose a new output directory; existing acceptance files are preserved")
    stages, checks, reports = [], [], {}
    with tempfile.TemporaryDirectory(prefix="b-http-") as temporary, socket.socket() as listener:
        isolated = Path(temporary)
        settings = Settings(
            username="b-http-check", password=secrets.token_urlsafe(24), secret=secrets.token_hex(32),
            auto_graph_sync=False, user_store=str(isolated / "users.json"),
            b_batch_registry=str(isolated / "ledger.json"), b_reviews_directory=str(isolated / "reviews"),
            b_source_offline=True, b_source_cache=str(isolated / "cache"),
            a_base_url="http://127.0.0.1:9", c_base_url="http://127.0.0.1:9",
        )
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="error", access_log=False))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        # HTTPX drives the local server; requests is solely the external-source
        # transport and must never be reached during this offline acceptance.
        with patch("requests.Session.get", side_effect=AssertionError("External-source HTTP is forbidden")):
            worker.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started:
                    if not worker.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("Isolated B HTTP server did not start")
                    time.sleep(.02)
                with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=120,
                                  trust_env=False) as client:
                    headers = {}

                    def get(path, **kwargs):
                        response = client.get(path, **kwargs)
                        response.raise_for_status()
                        return response.json()

                    def post(path, body):
                        response = client.post(path, json=body, headers=headers)
                        response.raise_for_status()
                        return response.json()

                    batch_path = "/api/admin/knowledge/batches"
                    report_path = "/api/admin/knowledge/report-export"
                    assert client.get(report_path).status_code == 401
                    login = post("/api/admin/sessions", dict(username=settings.username, password=settings.password))
                    headers["X-CSRF-Token"] = login["csrf_token"]
                    assert not get("/api/health")["graph_sync"]["automatic"]
                    checks.append("administrator_session_and_auto_publication_disabled")

                    def settled():
                        deadline = time.monotonic() + 30
                        while get(batch_path)["source_enrichment"]["running"]:
                            if time.monotonic() > deadline:
                                raise RuntimeError("Offline B source task did not settle")
                            time.sleep(.05)
                        return get(batch_path + "/readiness")

                    def capture(name, count):
                        ready = settled()
                        report = get(report_path, params={"expected_revision": ready["knowledge_revision"]})
                        validate_report_knowledge(report)
                        validate_effective(report["knowledge"])
                        assert report["scope"]["paper_count"] == count
                        assert ready["results"]["available"]
                        assert ready["publication"]["state"] == "not_checked"
                        reports[name] = report
                        stages.append(dict(stage=name, paper_count=count, source_state=ready["source_enrichment"]["state"],
                                           knowledge_revision=ready["knowledge_revision"], report_revision=report["revision"]))
                        print(f"B HTTP: {name}, {count} papers verified", file=sys.stderr, flush=True)
                        return report

                    documents = []
                    for name in ("01-first-batch.json", "02-second-batch.json"):
                        path = ROOT / "examples/week3_handoff" / name
                        body = path.read_bytes()
                        assert hashlib.sha256(body).hexdigest() == path.with_suffix(".json.sha256").read_text().split()[0]
                        documents.append(json.loads(body))
                    first = post(batch_path, dict(revision=get(batch_path)["revision"], document=documents[0], acknowledge_switch=True))
                    assert first["status"] == "accepted" and first["new"] == 20
                    first_report = capture("01-first", 20)
                    repeated = post(batch_path, dict(revision=get(batch_path)["revision"], document=documents[0], acknowledge_switch=True))
                    assert repeated["status"] == "unchanged"
                    second = post(batch_path, dict(revision=get(batch_path)["revision"], document=documents[1], acknowledge_switch=True))
                    assert (second["new"], second["duplicates"], second["updated"]) == (10, 7, 3)
                    merged = capture("02-merged", 30)
                    checks.extend(["real_A_checksums_and_20_to_30", "duplicate_batch_is_idempotent"])

                    # Human correction must affect tags/quality and undo exactly.
                    part = next(part for part in merged["knowledge"]["papers"]
                                if any(e["content"]["kind"] == "dataset" for e in part["entities"])
                                and any(r["content"]["kind"] == "has_author" for r in part["relations"]))
                    pid = part["input"]["openalex_id"]
                    dataset = next(item for item in part["entities"] if item["content"]["kind"] == "dataset")
                    mention = next(item for item in part["relations"] if item["content"]["kind"] == "mentions_dataset"
                                   and item["content"]["target"] == dataset["content"]["key"])

                    def decision(candidate_id, action, **extra):
                        view = get("/api/knowledge/paper", params={"paper_id": pid})
                        request = post("/api/knowledge/feedback", dict(
                            paper_id=pid, revision=view["revision"], candidate_id=candidate_id,
                            message="b-http-private-message", owner_token=secrets.token_hex(32)))
                        post("/api/admin/knowledge/feedback/" + request["id"], dict(
                            revision=get("/api/admin/knowledge/feedback")["revision"], action=action,
                            reason="b-http-private-reason", **extra))
                        return request["id"]

                    def undo(request_id):
                        post("/api/admin/knowledge/feedback/" + request_id + "/reopen",
                             dict(revision=get("/api/admin/knowledge/feedback")["revision"]))
                        assert get(report_path)["revision"] == merged["revision"]

                    corrected_name = dataset["content"]["name"] + " [B check]"
                    request_id = decision(dataset["candidate_id"], "rename", name=corrected_name)
                    corrected = get(report_path)
                    assert corrected["quality"]["review_states"]["human_corrected"] >= 1
                    assert any(corrected_name in tag["names"] for row in corrected["author_tags"]["authors"] for tag in row["tags"])
                    assert "b-http-private-message" not in json.dumps(corrected)
                    assert "b-http-private-reason" not in json.dumps(corrected)
                    undo(request_id)
                    request_id = decision(mention["candidate_id"], "exclude")
                    excluded = get(report_path)
                    assert any(item["candidate_id"] == dataset["candidate_id"]
                               for p in excluded["knowledge"]["papers"] for item in p["entities"])
                    assert not any(item["candidate_id"] == mention["candidate_id"]
                                   for row in excluded["author_tags"]["authors"] for tag in row["tags"]
                                   for support in tag["supports"] for item in support["witnesses"]["mention"])
                    undo(request_id)
                    checks.extend(["real_paper_feedback_rename_updates_tags_and_quality", "feedback_private_fields_not_exported",
                                   "excluding_relation_removes_support_without_removing_entity", "undo_restores_merged_report_revision"])

                    row = next(row for row in merged["author_tags"]["authors"] if row["tags"])
                    selected = get("/api/knowledge/author-tags", params={"author_ref": row["author_ref"],
                                                                                  "expected_revision": merged["scope"]["knowledge_revision"]})
                    assert selected["authors"] == [row]
                    effective = get("/api/admin/knowledge/effective-export", params={"expected_revision": selected["knowledge_revision"]})
                    assert effective["revision"] == merged["knowledge"]["revision"]
                    checks.extend(["author_identity_selection_and_explainable_supports", "effective_and_report_versions_agree"])

                    bad = deepcopy(documents[0])
                    bad.update(batch_id=999999, batch_code="B-HTTP-INVALID")
                    bad["items"][0]["year"] = "invalid"
                    failure = post(batch_path, dict(revision=get(batch_path)["revision"], document=bad, acknowledge_switch=True))
                    assert failure["status"] == "failed" and failure["accepted"] == 0
                    assert settled()["knowledge_revision"] == merged["scope"]["knowledge_revision"]
                    checks.append("HTTP_200_failed_receipt_does_not_change_effective")

                    withdrawn = post(batch_path + "/BATCH-000002/withdraw", dict(revision=get(batch_path)["revision"]))
                    assert (withdrawn["removed"], withdrawn["retained"], withdrawn["restored"]) == (10, 10, 3)
                    restored = capture("03-restored", 20)
                    assert restored["revision"] == first_report["revision"]
                    assert client.get(report_path, params={"expected_revision": merged["scope"]["knowledge_revision"]}).status_code == 409
                    post(batch_path + "/BATCH-000001/withdraw", dict(revision=get(batch_path)["revision"]))
                    empty = capture("04-empty", 0)
                    assert empty["author_tags"]["authors"] == []
                    assert empty["quality"]["evidence_coverage"]["ratio"] is None
                    assert post(batch_path + "/BATCH-000001/withdraw", dict(revision=get(batch_path)["revision"]))["status"] == "unchanged"
                    checks.extend(["withdrawal_restores_original_input_and_report_revision", "stale_expected_revision_is_409",
                                   "all_withdrawn_is_empty_not_demo_fallback", "repeated_withdrawal_is_idempotent"])
            finally:
                server.should_exit = True
                worker.join(timeout=15)
                if worker.is_alive():
                    server.force_exit = True
                    worker.join(timeout=5)
                    raise RuntimeError("Isolated HTTP server did not stop normally")
    summary = dict(format_version="b-http-acceptance/1", passed=True, stages=stages, checks=checks,
                   limits=["isolated loopback B HTTP, not team A/C/D integration", "offline source availability, not live external-provider acceptance",
                           "no browser acceptance or Neo4j publication"], server_stopped=True)
    if output_directory is not None:
        output_directory.mkdir(parents=True)
        for name, report in reports.items():
            (output_directory / (name + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="A new directory for four report examples and the acceptance summary")
    args = parser.parse_args()
    summary = verify(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
