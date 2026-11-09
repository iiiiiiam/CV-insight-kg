from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class ImportRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=200)


class KnowledgeReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    paper_id: str = Field(min_length=1, max_length=300)
    candidate_id: str = Field(min_length=1, max_length=128)
    action: Literal['confirm', 'reject', 'correct', 'reopen']
    reason: str = Field(min_length=1, max_length=2000)
    snapshot_revision: str = Field(pattern='^[0-9a-f]{64}$')
    name: str | None = Field(default=None, min_length=1, max_length=300)


class GraphImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_id: str = Field(pattern='^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')
    source_batch_id: str = Field(min_length=1, max_length=200)
    snapshot_revision: str = Field(pattern='^[0-9a-f]{64}$')
    digest: str = Field(pattern='^[0-9a-f]{64}$')


class GraphPublishRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_active_batch_id: str | None = Field(max_length=80)


class EffectiveGraphSyncRequest(BaseModel):
    """Pin the B public-knowledge revision that an administrator inspected."""
    model_config = ConfigDict(extra='forbid')
    expected_revision: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')


class OnlineJobRequest(BaseModel):
    venue: Literal['CVPR', 'ICCV', 'ECCV']
    year: int = Field(ge=1980, le=2100)
    source: Literal['cvf', 'ecva', 'openalex', 'dblp', 'auto'] = 'cvf'
    start: int = Field(default=1, ge=1, le=100000)
    count: int = Field(default=20, ge=1, le=100)


class FileImportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=30_000_000)
    manifest: dict


class SourceUpdateRequest(BaseModel):
    enabled: bool
    page_size: int = Field(ge=1, le=1000)
    max_retries: int = Field(ge=1, le=8)


class ReserveImportRequest(BaseModel):
    venue: Literal['CVPR','ICCV']
    year: int = Field(ge=1980,le=2100)
    source: Literal['openalex'] = 'openalex'
    count: int = Field(default=20,ge=1,le=100)
