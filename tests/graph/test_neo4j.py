"""Real Bolt/Neo4j integration. Requires an isolated disposable test database."""
import copy
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.graph_query.api import create_app
from src.graph_query.models import BatchInput
from src.graph_query.repository import GraphError, GraphRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("GRAPH_TEST_URI"),
    reason="set GRAPH_TEST_URI to an isolated disposable Neo4j instance",
)


@pytest.fixture(scope="module")
def repo():
    r = GraphRepository(
        os.environ["GRAPH_TEST_URI"],
        os.getenv("GRAPH_TEST_USER", "neo4j"),
        os.getenv("GRAPH_TEST_PASSWORD", "test-password"),
        os.getenv("GRAPH_TEST_DATABASE", "neo4j"),
    )
    r.initialize()
    yield r
    r.close()


@pytest.fixture
def batch():
    data = json.loads(
        (
            Path(__file__).resolve().parents[2] / "sample_data/graph/week1.json"
        ).read_text(encoding="utf-8")
    )
    data["batch_id"] = "test-" + uuid.uuid4().hex
    return BatchInput.model_validate(data)


def current(repo, batch):
    return repo.batch(batch.batch_id)["active_batch_id"]


def test_real_import_replay_filters_details_graph_and_publish(repo, batch):
    initial = repo.ingest(batch)
    assert not initial["replay"]
    assert repo.ingest(batch)["replay"]
    assert repo.batch(batch.batch_id)["checks"]["counts_match"]
    with pytest.raises(GraphError) as e:
        repo.papers({}, batch.batch_id)
    assert e.value.code == "PUBLISHED_BATCH_NOT_FOUND"
    before = current(repo, batch)
    with pytest.raises(GraphError) as e:
        repo.publish(batch.batch_id, before)
    assert e.value.code == "FIXTURE_REQUIRES_OPT_IN"
    assert current(repo, batch) == before
    repo.publish(batch.batch_id, before, True)
    assert repo.papers({}, batch.batch_id)["total"] == 5
    assert repo.papers({"year": 2023}, batch.batch_id)["total"] == 0
    assert (
        repo.papers({"year": 2024, "topic": "Object Detection"}, batch.batch_id)[
            "total"
        ]
        == 5
    )
    assert (
        repo.papers(
            {"topic": "Object Detection", "method": "YOLO", "year": 2024},
            batch.batch_id,
        )["total"]
        == 2
    )
    assert (
        repo.papers(
            {
                "topic": "Object Detection",
                "method": "Knowledge Distillation",
                "year": 2024,
            },
            batch.batch_id,
        )["total"]
        == 1
    )
    assert repo.papers({"q": "' OR 1=1 //"}, batch.batch_id)["total"] == 0
    page = repo.papers({}, batch.batch_id, page=2, page_size=2, sort="title")
    assert len(page["items"]) == 2 and page["total"] == 5
    first = repo.papers({}, batch.batch_id, sort="title")["items"][0]
    detail = repo.detail(first["id"], batch.batch_id, "paper")
    assert detail["relations"] and all(r["evidence"] for r in detail["relations"])
    one = repo.graph(first["id"], 1, batch.batch_id)
    two = repo.graph(first["id"], 2, batch.batch_id)
    assert len(two["nodes"]) > len(one["nodes"])
    assert all(n["batch_id"] == batch.batch_id for n in two["nodes"])
    limited = repo.graph(first["id"], 2, batch.batch_id, 1)
    assert limited["truncated"]
    filtered = repo.graph(first["id"], 2, batch.batch_id, types=["published_in"])
    assert all(e["kind"] == "published_in" for e in filtered["edges"])
    empty = repo.graph(first["id"], 2, batch.batch_id, filters={"year": 2023})
    assert not empty["edges"]
    with pytest.raises(GraphError):
        repo.detail("nonexistent", batch.batch_id)
    with TestClient(create_app(repo, admin_token="test-token")) as c:
        assert (
            c.get(
                "/api/research/papers?topic=Object%20Detection&method=YOLO&year=2024"
            ).json()["total"]
            == 2
        )
        assert (
            c.get(
                "/api/research/graph",
                params={"seed": first["id"], "hops": 2, "batch_id": batch.batch_id},
            ).status_code
            == 200
        )
        assert (
            c.get(
                "/api/research/papers/" + first["id"],
                params={"batch_id": batch.batch_id},
            ).json()["node"]["title"]
            == first["title"]
        )


def test_real_immutability_and_batch_isolation(repo, batch):
    repo.ingest(batch)
    changed = batch.model_copy(deep=True)
    changed.entities[0].name += " changed"
    with pytest.raises(GraphError) as e:
        repo.ingest(changed)
    assert e.value.code == "BATCH_IMMUTABLE"
    active = current(repo, batch)
    repo.publish(batch.batch_id, active, True)
    second = batch.model_copy(deep=True)
    second.batch_id += "-next"
    second.entities[0].name += " new version"
    repo.ingest(second)
    repo.publish(second.batch_id, batch.batch_id, True)
    assert repo.papers({})["batch_id"] == second.batch_id
    assert (
        repo.detail(batch.entities[0].id, batch.batch_id)["node"]["name"]
        == batch.entities[0].name
    )
    assert repo.detail(batch.entities[0].id, second.batch_id)["node"]["name"].endswith(
        "new version"
    )
    with pytest.raises(GraphError) as e:
        repo.publish(batch.batch_id, batch.batch_id, True)
    assert e.value.code == "ACTIVE_BATCH_CHANGED"
    assert repo.papers({})["batch_id"] == second.batch_id


def test_real_concurrent_import_is_idempotent(repo, batch):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.ingest(batch), range(2)))
    assert sorted(r["replay"] for r in results) == [False, True]
    assert repo.batch(batch.batch_id)["checks"]["counts_match"]


def test_real_publish_cas_has_one_winner(repo, batch):
    second = batch.model_copy(deep=True)
    second.batch_id += "-second"
    repo.ingest(batch)
    repo.ingest(second)
    expected = current(repo, batch)

    def publish(id):
        try:
            repo.publish(id, expected, True)
            return "ok"
        except GraphError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [batch.batch_id, second.batch_id]))
    assert sorted(results) == ["ACTIVE_BATCH_CHANGED", "ok"]


def test_real_affiliation_requires_same_paper_evidence(repo, batch):
    from src.graph_query.models import Entity, Link, Evidence

    paper = batch.entities[0]
    authored = next(
        r for r in batch.relations if r.source == paper.id and r.kind == "has_author"
    )
    batch.entities.append(
        Entity(
            id="institution:test",
            kind="institution",
            name="Test Institution",
            updated_at=paper.updated_at,
        )
    )
    batch.relations.append(
        Link(
            source=authored.target,
            target="institution:test",
            kind="affiliated_with",
            status="confirmed",
            evidence=[
                Evidence(
                    paper_id=paper.id,
                    source_url=paper.source_url,
                    field="metadata",
                    quote="test institution evidence",
                    locator="test-only",
                    reviewer="automated-test",
                    reviewed_at=paper.updated_at,
                )
            ],
        )
    )
    repo.ingest(batch)
    repo.publish(batch.batch_id, current(repo, batch), True)
    result = repo.papers({"institution": "Test Institution"}, batch.batch_id)
    assert [p["id"] for p in result["items"]] == [paper.id]
    assert (
        repo.entities("Test Institution", "institution", batch.batch_id)["items"][0][
            "id"
        ]
        == "institution:test"
    )


def test_real_mid_import_failure_rolls_back(repo, batch, monkeypatch):
    original = repo.run

    def fail_after_nodes(operation, *, write=False):
        def wrapped(tx):
            class FailingTx:
                def run(self, query, *args, **kwargs):
                    if query.startswith("UNWIND $links"):
                        raise RuntimeError("simulated failure after writing nodes")
                    return tx.run(query, *args, **kwargs)

            return operation(FailingTx())

        return original(wrapped, write=write)

    with monkeypatch.context() as patch:
        patch.setattr(repo, "run", fail_after_nodes)
        with pytest.raises(RuntimeError):
            repo.ingest(batch)
    with pytest.raises(GraphError) as e:
        repo.batch(batch.batch_id)
    assert e.value.code == "BATCH_NOT_FOUND"
    count = repo.run(
        lambda tx: tx.run(
            "MATCH (n:CVEntity {batch_id:$batch}) RETURN count(n) AS n",
            batch=batch.batch_id,
        ).single()["n"]
    )
    assert count == 0


def test_real_failed_quality_check_preserves_active(repo, batch):
    repo.ingest(batch)
    old = current(repo, batch)
    # Test-only fault injection, restricted to this test's unique batch.
    repo.run(
        lambda tx: tx.run(
            "MATCH (:CVEntity {batch_id:$batch})-[r:CV_LINK]->() WITH r LIMIT 1 DELETE r",
            batch=batch.batch_id,
        ).consume(),
        write=True,
    )
    with pytest.raises(GraphError) as e:
        repo.publish(batch.batch_id, old, True)
    assert e.value.code == "QUALITY_CHECK_FAILED"
    assert current(repo, batch) == old
