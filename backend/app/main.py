"""Entrix AI — FastAPI application.

Provides the API surface for authentication, document ingestion, RAG queries,
agentic action execution, and audit access.

All endpoints enforce authentication. Document content is never exposed
without server-side authorization checks.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import execute_action, get_available_actions
from app.audit import AuditEventType, record_audit_event
from app.config import get_settings
from app.database import async_session_factory, get_db, init_db
from app.generation import generate_abstention_response, generate_answer, get_llm_provider
from app.ingestion import ingest_document
from app.models import ActionExecution, AuditLog, Document, QueryRecord, User
from app.retrieval import RetrievalEngine
from app.schemas import (
    ActionHistoryItem,
    ActionRequest,
    ActionResponse,
    AuditEntry,
    DocumentSummary,
    ErrorResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    LoginRequest,
    QueryRequest,
    QueryResponse,
    SufficiencyDecision,
    TokenResponse,
    UserInfo,
)
from app.security import (
    create_access_token,
    get_current_user,
    require_role,
    verify_password,
)
from app.sufficiency import EvidenceSufficiencyController, get_estimator

_settings = get_settings()
logger = structlog.get_logger(__name__)

# ── Application setup ────────────────────────────────────────────────────

app = FastAPI(
    title="Entrix AI",
    description="Enterprise Intelligence & Agentic Automation Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Vite may be opened through either localhost or the 127.0.0.1 loopback
    # address; both are local development origins, but browsers treat them as
    # distinct origins for CORS purposes.
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global retrieval engine instance
_retrieval_engine: RetrievalEngine | None = None


def get_retrieval_engine() -> RetrievalEngine:
    global _retrieval_engine
    if _retrieval_engine is None:
        _retrieval_engine = RetrievalEngine()
    return _retrieval_engine


# ── Middleware ───────────────────────────────────────────────────────────


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add a correlation ID to every request for audit trail linkage."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    start = time.monotonic()
    response = await call_next(request)
    duration = (time.monotonic() - start) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Response-Time-Ms"] = f"{duration:.1f}"
    return response


# ── Lifecycle ────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    await init_db()
    async with async_session_factory() as db:
        await get_retrieval_engine().hydrate(db)
    logger.info("application_started", version="0.1.0")


# ── Exception handlers ──────────────────────────────────────────────────


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=str(exc.detail),
            correlation_id=correlation_id,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.error("unhandled_error", error=str(exc), correlation_id=correlation_id)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            correlation_id=correlation_id,
        ).model_dump(),
    )


# ── Health ───────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


# ── Authentication ───────────────────────────────────────────────────────


@app.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT token.

    This is a DEVELOPMENT authentication mechanism. In production, use a
    proper identity provider (OAuth2/OIDC).
    """
    result = await db.execute(
        select(User).where(User.username == request.username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(request.password, user.hashed_password):
        await record_audit_event(
            db,
            AuditEventType.AUTH_LOGIN_FAILED,
            details={"username": request.username, "reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(user.id, user.organization_id, user.role)

    await record_audit_event(
        db,
        AuditEventType.AUTH_LOGIN,
        user_id=user.id,
        organization_id=user.organization_id,
        details={"username": user.username},
    )

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else "",
        role=user.role,
    )


@app.get("/auth/me", response_model=UserInfo)
async def get_me(user: User = Depends(get_current_user)):
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else "",
    )


# ── Documents ────────────────────────────────────────────────────────────


@app.get("/documents", response_model=list[DocumentSummary])
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents the current user is authorized to access."""
    result = await db.execute(
        select(Document).where(Document.organization_id == user.organization_id)
    )
    docs = result.scalars().all()

    # Filter by role-based access
    from app.security import check_document_access

    return [
        DocumentSummary(
            id=doc.id,
            title=doc.title,
            source_id=doc.source_id,
            version=doc.version,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
        )
        for doc in docs
        if check_document_access(user, doc)
    ]


@app.post("/documents/ingest", response_model=IngestResponse)
async def ingest(
    request: IngestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a new document. Requires editor role or above."""
    require_role(user, "editor")

    engine = get_retrieval_engine()
    doc = await ingest_document(
        db,
        engine,
        organization_id=user.organization_id,
        title=request.title,
        content=request.content,
        source_id=request.source_id,
        allowed_roles=request.allowed_roles,
    )

    await record_audit_event(
        db,
        AuditEventType.DOCUMENT_INGESTED,
        user_id=user.id,
        organization_id=user.organization_id,
        resource_type="document",
        resource_id=doc.id,
        details={"title": doc.title, "chunks": doc.chunk_count},
    )

    return IngestResponse(
        document_id=doc.id,
        title=doc.title,
        chunk_count=doc.chunk_count,
        message=f"Document '{doc.title}' ingested with {doc.chunk_count} chunks",
    )


# ── RAG Query ────────────────────────────────────────────────────────────


@app.post("/query", response_model=QueryResponse)
async def query_rag(
    request: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute the full RAG pipeline: retrieve → assess → answer/retry/abstain.

    This endpoint implements the core research pipeline:
    1. Authorized hybrid retrieval.
    2. Evidence sufficiency assessment (configurable estimator).
    3. If insufficient: one authorized retry attempt.
    4. If still insufficient: structured abstention.
    5. If sufficient: answer generation with citation validation.
    """
    correlation_id = str(uuid.uuid4())
    start = time.monotonic()

    engine = get_retrieval_engine()
    estimator_name = request.estimator or _settings.sufficiency_estimator
    controller = EvidenceSufficiencyController(get_estimator(estimator_name))

    # Step 1: Authorized retrieval
    evidence = await engine.search(request.query, user, db, top_k=request.top_k)

    await record_audit_event(
        db,
        AuditEventType.RETRIEVAL_EXECUTED,
        user_id=user.id,
        organization_id=user.organization_id,
        details={"query_length": len(request.query), "evidence_count": len(evidence)},
        correlation_id=correlation_id,
    )

    # Step 2: Sufficiency assessment
    assessment = await controller.evaluate(request.query, evidence)
    retry_attempted = False

    await record_audit_event(
        db,
        AuditEventType.SUFFICIENCY_ASSESSED,
        user_id=user.id,
        organization_id=user.organization_id,
        details={
            "decision": assessment.decision.value,
            "score": assessment.coverage_score,
            "estimator": estimator_name,
        },
        correlation_id=correlation_id,
    )

    # Step 3: Retry if insufficient (max 1 attempt)
    if assessment.decision == SufficiencyDecision.INSUFFICIENT and evidence:
        retry_query = controller.generate_retry_query(request.query, assessment)
        if retry_query:
            retry_attempted = True
            additional_evidence = await engine.search(retry_query, user, db, top_k=request.top_k)

            # Merge and deduplicate
            seen_ids = {e.evidence_id for e in evidence}
            for ev in additional_evidence:
                if ev.evidence_id not in seen_ids:
                    evidence.append(ev)
                    seen_ids.add(ev.evidence_id)

            # Reassess
            assessment = await controller.evaluate(request.query, evidence)

            await record_audit_event(
                db,
                AuditEventType.SUFFICIENCY_RETRY,
                user_id=user.id,
                organization_id=user.organization_id,
                details={
                    "decision": assessment.decision.value,
                    "score": assessment.coverage_score,
                    "new_evidence_count": len(additional_evidence),
                },
                correlation_id=correlation_id,
            )

    latency_ms = round((time.monotonic() - start) * 1000, 2)

    # Step 4: Generate answer or abstain
    if assessment.decision == SufficiencyDecision.SUFFICIENT and evidence:
        llm = get_llm_provider()
        answer_text, citations = await generate_answer(request.query, evidence, llm)

        await record_audit_event(
            db,
            AuditEventType.GENERATION_COMPLETED,
            user_id=user.id,
            organization_id=user.organization_id,
            details={"citation_count": len(citations)},
            correlation_id=correlation_id,
        )

        # Save query record
        record = QueryRecord(
            user_id=user.id,
            organization_id=user.organization_id,
            query_text=request.query,
            answer_text=answer_text,
            abstained=False,
            sufficiency_score=assessment.coverage_score,
            evidence_ids=[e.evidence_id for e in evidence],
            retry_attempted=retry_attempted,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
        )
        db.add(record)
        await db.flush()

        return QueryResponse(
            query_id=record.id,
            query=request.query,
            answer=answer_text,
            abstained=False,
            citations=citations,
            evidence=evidence,
            sufficiency=assessment,
            retry_attempted=retry_attempted,
            latency_ms=latency_ms,
        )
    else:
        # Abstain
        abstention_msg = await generate_abstention_response(request.query, assessment.rationale)

        await record_audit_event(
            db,
            AuditEventType.GENERATION_ABSTAINED,
            user_id=user.id,
            organization_id=user.organization_id,
            details={
                "reason": assessment.rationale,
                "score": assessment.coverage_score,
            },
            correlation_id=correlation_id,
        )

        record = QueryRecord(
            user_id=user.id,
            organization_id=user.organization_id,
            query_text=request.query,
            abstained=True,
            sufficiency_score=assessment.coverage_score,
            evidence_ids=[e.evidence_id for e in evidence],
            retry_attempted=retry_attempted,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
        )
        db.add(record)
        await db.flush()

        return QueryResponse(
            query_id=record.id,
            query=request.query,
            answer=None,
            abstained=True,
            abstention_reason=abstention_msg,
            evidence=evidence,
            sufficiency=assessment,
            retry_attempted=retry_attempted,
            latency_ms=latency_ms,
        )


# ── Actions ──────────────────────────────────────────────────────────────


@app.get("/actions/available")
async def list_actions(user: User = Depends(get_current_user)):
    """List available enterprise actions."""
    return get_available_actions()


@app.post("/actions/execute", response_model=ActionResponse)
async def execute_enterprise_action(
    request: ActionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a controlled enterprise action with full authorization."""
    return await execute_action(
        db,
        user,
        request.action_name,
        request.parameters,
        request.idempotency_key,
    )


@app.get("/actions/history", response_model=list[ActionHistoryItem])
async def action_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's action execution history."""
    result = await db.execute(
        select(ActionExecution)
        .where(
            ActionExecution.user_id == user.id,
            ActionExecution.organization_id == user.organization_id,
        )
        .order_by(ActionExecution.created_at.desc())
        .limit(50)
    )
    executions = result.scalars().all()

    return [
        ActionHistoryItem(
            id=e.id,
            action_name=e.action_name,
            status=e.status,
            parameters=e.parameters,
            result=e.result,
            error_message=e.error_message,
            created_at=e.created_at,
            executed_at=e.executed_at,
        )
        for e in executions
    ]


# ── Audit ────────────────────────────────────────────────────────────────


@app.get("/admin/audit", response_model=list[AuditEntry])
async def get_audit_log(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """View audit log. Admin role required."""
    require_role(user, "admin")

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.organization_id == user.organization_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(min(limit, 200))
    )
    logs = result.scalars().all()

    return [
        AuditEntry(
            id=log.id,
            event_type=log.event_type,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            user_id=log.user_id,
            details=log.details,
            correlation_id=log.correlation_id,
            timestamp=log.timestamp,
        )
        for log in logs
    ]
