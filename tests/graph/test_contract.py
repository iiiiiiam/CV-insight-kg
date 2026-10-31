import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.graph_query.api import create_app
from src.graph_query.b_adapter import adapt_confirmed
from src.graph_query.models import BatchInput
from src.graph_query.repository import GraphError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def payload():
    return json.loads(
        (ROOT / "sample_data/graph/week1.json").read_text(encoding="utf-8")
    )


def test_fixture_is_explicit_and_valid(payload):
    batch = BatchInput.model_validate(payload)
    assert batch.provenance == "developer_fixture"
    assert sum(n.kind == "paper" for n in batch.entities) == 5
    assert len(batch.relations) > 5


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_entity",
        "dangling",
        "wrong_type",
        "pending",
        "no_evidence",
        "fake_quote",
        "wrong_paper",
        "unknown_field",
    ],
)
def test_reject_invalid_graph(payload, change):
    if change == "duplicate_entity":
        payload["entities"].append(payload["entities"][0])
    elif change == "dangling":
        payload["relations"][0]["target"] = "missing"
    elif change == "wrong_type":
        payload["relations"][0]["kind"] = "has_author"
    elif change == "pending":
        payload["relations"][0]["status"] = "pending"
    elif change == "no_evidence":
        payload["relations"][0]["evidence"] = []
    elif change == "fake_quote":
        payload["relations"][0]["evidence"][0].update(
            field="title", quote="fabricated evidence"
        )
    elif change == "wrong_paper":
        payload["relations"][0]["evidence"][0]["paper_id"] = "missing"
    else:
        payload["unexpected"] = "x"
    with pytest.raises(ValidationError):
        BatchInput.model_validate(payload)


def test_content_hash_stable_under_node_order(payload):
    first = BatchInput.model_validate(payload)
    payload["entities"].reverse()
    payload["relations"].reverse()
    assert first.digest() == BatchInput.model_validate(payload).digest()
    payload["entities"][0]["name"] += " changed"
    assert first.digest() != BatchInput.model_validate(payload).digest()


def test_b_export_refuses_pending_and_empty():
    with pytest.raises(ValueError):
        adapt_confirmed({"status": "pending"}, "x", "a")
    with pytest.raises(ValueError):
        adapt_confirmed(
            {
                "format_version": "b-knowledge-export/0.1-draft",
                "status": "confirmed",
                "kind": "confirmed_knowledge",
                "papers": [],
            },
            "x",
            "a",
        )


def b_example():
    raw = dict(
        openalex_id="https://openalex.org/W1",
        title="Real source title",
        abstract=None,
        year=2024,
        venue="CVPR",
        authorships=[],
        source_url="https://openalex.org/W1",
        dataset_id="test",
    )
    digest = hashlib.sha256(
        json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    review = dict(
        action="confirm",
        reviewer="test-only",
        reason="test fixture",
        occurred_at="2026-10-31T00:00:00Z",
    )

    def entry(content, evidence=None):
        return dict(
            item=dict(content=content, status="confirmed", evidence=evidence or []),
            review=review,
        )

    evidence = dict(
        paper_id=raw["openalex_id"],
        source_url=raw["source_url"],
        input_fingerprint=digest,
        field="metadata",
        quote='"CVPR"',
        path=["venue"],
        start=None,
        end=None,
    )
    part = dict(
        input=raw,
        origin=dict(
            input_fingerprint=digest,
            source_schema_version="b-knowledge/0.1-draft",
            vocabulary_version="test",
        ),
        endpoint_context=[],
        entities=[
            entry(
                dict(
                    key="p1",
                    kind="paper",
                    name=raw["title"],
                    source_id=raw["openalex_id"],
                )
            ),
            entry(dict(key="v1", kind="venue", name="CVPR", source_id=None)),
        ],
        relations=[
            entry(dict(source="p1", kind="published_in", target="v1"), [evidence])
        ],
    )
    return dict(
        format_version="b-knowledge-export/0.1-draft",
        status="confirmed",
        kind="confirmed_knowledge",
        papers=[part],
    )


def test_b_adapter_verified_metadata_and_no_mutation():
    source = b_example()
    saved = copy.deepcopy(source)
    batch = adapt_confirmed(source, "test-b", "a")
    assert (
        batch.provenance == "reviewed_export"
        and batch.relations[0].evidence[0].paper_id == "p1"
    )
    assert source == saved


@pytest.mark.parametrize(
    "change", ["fingerprint", "metadata", "review", "pending", "endpoint_context"]
)
def test_b_adapter_refuses_tampering(change):
    source = b_example()
    p = source["papers"][0]
    if change == "fingerprint":
        p["input"]["title"] = "changed"
    elif change == "metadata":
        p["relations"][0]["item"]["evidence"][0]["quote"] = '"fake"'
    elif change == "review":
        p["relations"][0]["review"]["action"] = "reopen"
    elif change == "pending":
        p["relations"][0]["item"]["status"] = "pending"
    else:
        p["endpoint_context"] = [{}]
    with pytest.raises(ValueError):
        adapt_confirmed(source, "test-b", "a")


class BoundaryRepo:
    def initialize(self):
        pass

    def ingest(self, body):
        return {"batch_id": body.batch_id}

    def papers(self, *args):
        raise GraphError(404, "PUBLISHED_BATCH_NOT_FOUND", "尚无已发布批次")


@pytest.fixture
def client():
    with TestClient(create_app(BoundaryRepo(), admin_token="test-secret")) as client:
        yield client


def test_admin_rejects_anonymous_and_wrong_token(client, payload):
    for headers in ({}, {"Authorization": "Bearer incorrect"}):
        assert (
            client.post(
                "/api/admin/graph/batches", json=payload, headers=headers
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/admin/graph/batches",
            json=payload,
            headers={"Authorization": "Bearer test-secret"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "query", ["year=1800", "hops=3", "limit=201", "types=INJECT", "hops=0"]
)
def test_graph_parameter_boundaries(client, query):
    assert client.get("/api/research/graph?seed=x&" + query).status_code == 422


def test_no_published_batch_has_clear_error(client):
    r = client.get("/api/research/papers")
    assert (
        r.status_code == 404
        and r.json()["error"]["code"] == "PUBLISHED_BATCH_NOT_FOUND"
    )


def test_admin_unconfigured_is_fail_closed(payload):
    with TestClient(create_app(BoundaryRepo(), admin_token="")) as c:
        assert c.post("/api/admin/graph/batches", json=payload).status_code == 503


def test_openapi_and_component(client):
    schema = client.get("/openapi.json").json()
    assert "/api/research/graph" in schema["paths"]
    html = client.get("/research").text
    assert "mountPaperDetail" in html and "textContent" in html
    assert (
        "export function mountPaperDetail"
        in client.get("/assets/c-paper-detail.js").text
    )
