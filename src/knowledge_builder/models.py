"""B 输入及待审核候选模型；不依赖数据库或页面。"""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class PaperInput:
    """供抽取使用的论文；authorships 保留来源中的作者与机构结构。"""

    openalex_id: str
    title: str
    abstract: str | None
    year: int
    venue: str
    authorships: list[dict[str, Any]]
    source_url: str
    dataset_id: str


EntityType = Literal[
    "paper", "author", "institution", "topic", "method", "task", "dataset", "venue"
]


@dataclass(frozen=True)
class Entity:
    key: str
    kind: EntityType
    name: str
    source_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    """文本用字符切片；元数据用相对 PaperInput 的路径和精确 JSON 值。"""

    paper_id: str
    dataset_id: str
    source_url: str
    input_fingerprint: str
    field: str
    quote: str
    start: int | None = None
    end: int | None = None
    path: tuple[str | int, ...] = ()


@dataclass
class EntityCandidate:
    candidate_id: str
    entity: Entity
    evidence: list[Evidence]
    status: Literal["pending"] = "pending"


@dataclass
class RelationCandidate:
    candidate_id: str
    source: str
    kind: str
    target: str
    evidence: list[Evidence]
    status: Literal["pending"] = "pending"


@dataclass
class ExtractionResult:
    paper_id: str
    input_fingerprint: str
    schema_version: str
    rule_version: str
    vocabulary_version: str
    vocabulary_fingerprint: str
    entities: list[EntityCandidate]
    relations: list[RelationCandidate]
    diagnostics: list[str]
