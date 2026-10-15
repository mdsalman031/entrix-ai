"""Pydantic v2 schemas for API request/response validation.

Every API boundary uses typed schemas. Internal authorization metadata is
never exposed to ordinary users.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Auth ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    organization_id: str
    organization_name: str
    role: str


class UserInfo(BaseModel):
    id: str
    username: str
    email: str
    role: str
    organization_id: str
    organization_name: str


# ── Documents ────────────────────────────────────────────────────────────


class DocumentSummary(BaseModel):
    id: str
    title: str
    source_id: str | None = None
    version: int
    chunk_count: int
    created_at: datetime


class IngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=500_000)
    source_id: str | None = None
    allowed_roles: list[str] = Field(default_factory=lambda: ["viewer", "editor", "admin"])


class IngestResponse(BaseModel):
    document_id: str
    title: str
    chunk_count: int
    message: str


# ── Evidence & Retrieval ─────────────────────────────────────────────────


class EvidenceItem(BaseModel):
    """A single piece of authorized evidence returned by retrieval."""

    evidence_id: str
    document_id: str
    document_title: str
    chunk_index: int
    text: str
    score: float
    source_id: str | None = None


class SufficiencyDecision(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    RETRY = "retry"
    ABSTAIN = "abstain"


class SufficiencyAssessment(BaseModel):
    """Structured output of the evidence-sufficiency controller."""

    decision: SufficiencyDecision
    coverage_score: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""


# ── Query / RAG ──────────────────────────────────────────────────────────


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    estimator: Literal["heuristic", "structured", "llm"] | None = None


class Citation(BaseModel):
    document_id: str
    document_title: str
    chunk_index: int
    source_id: str | None = None
    excerpt: str = ""


class QueryResponse(BaseModel):
    query_id: str
    query: str
    answer: str | None = None
    abstained: bool = False
    abstention_reason: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    sufficiency: SufficiencyAssessment | None = None
    retry_attempted: bool = False
    latency_ms: float = 0.0


# ── Actions ──────────────────────────────────────────────────────────────


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_name: str = Field(..., min_length=1, max_length=100)
    parameters: dict = Field(default_factory=dict)
    idempotency_key: str | None = None


class ActionResponse(BaseModel):
    execution_id: str
    action_name: str
    status: ActionStatus
    result: dict | None = None
    error_message: str | None = None
    correlation_id: str
    policy_version: int | None = None


class ActionHistoryItem(BaseModel):
    id: str
    action_name: str
    status: str
    parameters: dict
    result: dict | None = None
    error_message: str | None = None
    created_at: datetime
    executed_at: datetime | None = None


# ── Audit ────────────────────────────────────────────────────────────────


class AuditEntry(BaseModel):
    id: str
    event_type: str
    resource_type: str | None = None
    resource_id: str | None = None
    user_id: str | None = None
    details: dict
    correlation_id: str | None = None
    timestamp: datetime


# ── Health ───────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


# ── Errors ───────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    correlation_id: str | None = None


# ── Evaluation ───────────────────────────────────────────────────────────


class EvalQueryResult(BaseModel):
    """Per-query result used for offline evaluation."""

    query_id: str
    query_text: str
    baseline: str
    expected_answerable: bool | None = None
    answered: bool
    abstained: bool
    answer_text: str | None = None
    evidence_count: int = 0
    authorized_recall: float | None = None
    citation_valid: bool | None = None
    sufficiency_score: float | None = None
    retry_attempted: bool = False
    latency_ms: float = 0.0
    error: str | None = None


class EvalAggregateMetrics(BaseModel):
    """Aggregate metrics across an evaluation run."""

    baseline: str
    total_queries: int
    answered_count: int
    abstained_count: int
    error_count: int
    mean_latency_ms: float
    abstention_precision: float | None = None
    abstention_recall: float | None = None
    answer_coverage: float | None = None
    mean_authorized_recall: float | None = None
    mean_sufficiency_score: float | None = None
    citation_validity_rate: float | None = None
