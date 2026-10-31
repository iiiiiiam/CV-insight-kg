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
