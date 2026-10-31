"""Versioned, strict graph input contract. Pending knowledge never enters this model."""
import hashlib
import json
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
)

EntityKind = Literal[
    "paper", "author", "institution", "topic", "method", "task", "dataset", "venue"
]
RELATIONS = {
    "has_author": ("paper", "author"),
    "affiliated_with": ("author", "institution"),
    "published_in": ("paper", "venue"),
    "mentions_topic": ("paper", "topic"),
    "mentions_method": ("paper", "method"),
    "mentions_task": ("paper", "task"),
    "mentions_dataset": ("paper", "dataset"),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(StrictModel):
    paper_id: str = Field(min_length=1, max_length=500)
    source_url: HttpUrl
    field: Literal["title", "abstract", "metadata"]
    quote: str = Field(min_length=1, max_length=20000)
    locator: str = Field(min_length=1, max_length=1000)
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_at: AwareDatetime


class Entity(StrictModel):
    id: str = Field(min_length=1, max_length=500)
    kind: EntityKind
    name: str = Field(min_length=1, max_length=2000)
    year: int | None = Field(default=None, ge=1900, le=2100)
    abstract: str | None = Field(default=None, max_length=100000)
    source_url: HttpUrl | None = None
    source_id: str | None = None
    updated_at: AwareDatetime
    missing_fields: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def paper_metadata(self):
        if self.kind == "paper" and (self.year is None or self.source_url is None):
            raise ValueError("paper requires year and source_url")
        return self


class Link(StrictModel):
    source: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    kind: Literal[
        "has_author",
        "affiliated_with",
        "published_in",
        "mentions_topic",
        "mentions_method",
        "mentions_task",
        "mentions_dataset",
    ]
    status: Literal["confirmed"]
    evidence: list[Evidence] = Field(min_length=1, max_length=50)


class BatchInput(StrictModel):
    contract_version: Literal["c-graph/1.0"]
    batch_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
    source_batch_id: str = Field(min_length=1, max_length=200)
    schema_version: str = Field(min_length=1, max_length=100)
    vocabulary_version: str = Field(min_length=1, max_length=100)
    provenance: Literal["reviewed_export", "developer_fixture"]
    entities: list[Entity] = Field(min_length=1, max_length=10000)
    relations: list[Link] = Field(max_length=30000)

    @model_validator(mode="after")
    def validate_graph(self):
        nodes = {n.id: n for n in self.entities}
        if len(nodes) != len(self.entities):
            raise ValueError("duplicate entity id")
        if not any(n.kind == "paper" for n in nodes.values()):
            raise ValueError("batch requires at least one paper")
        seen = set()
        for r in self.relations:
            if r.source not in nodes or r.target not in nodes:
                raise ValueError("dangling relationship endpoint")
            if (nodes[r.source].kind, nodes[r.target].kind) != RELATIONS[r.kind]:
                raise ValueError("relationship endpoint types do not match schema")
            key = (r.source, r.kind, r.target)
            if key in seen:
                raise ValueError("duplicate relationship")
            seen.add(key)
            for e in r.evidence:
                if e.paper_id not in nodes or nodes[e.paper_id].kind != "paper":
                    raise ValueError(
                        "evidence must reference a paper in the same batch"
                    )
                if nodes[r.source].kind == "paper" and e.paper_id != r.source:
                    raise ValueError(
                        "paper relation evidence must refer to its source paper"
                    )
                if e.field in ("title", "abstract"):
                    text = (
                        nodes[e.paper_id].name
                        if e.field == "title"
                        else nodes[e.paper_id].abstract
                    )
                    if not text or e.quote not in text:
                        raise ValueError("evidence quote is absent from source text")
        return self

    def digest(self):
        data = self.model_dump(mode="json")
        data["entities"] = sorted(data["entities"], key=lambda n: n["id"])
        data["relations"] = sorted(
            data["relations"], key=lambda r: (r["source"], r["kind"], r["target"])
        )
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


class PublishInput(StrictModel):
    expected_active_batch_id: str | None
    allow_developer_fixture: bool = False
