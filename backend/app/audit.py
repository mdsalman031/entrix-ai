"""Audit trail for security-relevant and research-relevant events.

Records authentication decisions, retrieval attempts, sufficiency assessments,
answer generation, abstentions, action executions, and security violations.

Audit entries contain enough information to reconstruct a decision pathway
without exposing restricted document contents or secrets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = structlog.get_logger(__name__)


class AuditEventType:
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"

    # Retrieval
    RETRIEVAL_EXECUTED = "retrieval.executed"
    RETRIEVAL_UNAUTHORIZED_FILTERED = "retrieval.unauthorized_filtered"

    # Sufficiency
    SUFFICIENCY_ASSESSED = "sufficiency.assessed"
    SUFFICIENCY_RETRY = "sufficiency.retry"

    # Generation
    GENERATION_COMPLETED = "generation.completed"
    GENERATION_ABSTAINED = "generation.abstained"
    GENERATION_CITATION_INVALID = "generation.citation_invalid"

    # Actions
    ACTION_PROPOSED = "action.proposed"
    ACTION_AUTHORIZED = "action.authorized"
    ACTION_EXECUTED = "action.executed"
    ACTION_REJECTED = "action.rejected"
    ACTION_FAILED = "action.failed"
    ACTION_STALE_POLICY = "action.stale_policy"

    # Security
    SECURITY_CROSS_TENANT = "security.cross_tenant_attempt"
    SECURITY_UNAUTHORIZED_ACCESS = "security.unauthorized_access"
    SECURITY_FABRICATED_ID = "security.fabricated_evidence_id"

    # Ingestion
    DOCUMENT_INGESTED = "document.ingested"
    DOCUMENT_DELETED = "document.deleted"


async def record_audit_event(
    db: AsyncSession,
    event_type: str,
    *,
    user_id: str | None = None,
    organization_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    correlation_id: str | None = None,
) -> AuditLog:
    """Persist an audit event. Never include restricted document text or secrets in details."""
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    # Sanitize details to remove any accidental sensitive data
    safe_details = _sanitize_details(details or {})

    entry = AuditLog(
        user_id=user_id,
        organization_id=organization_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=safe_details,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
    db.add(entry)

    logger.info(
        "audit_event",
        event_type=event_type,
        user_id=user_id,
        org_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        correlation_id=correlation_id,
    )

    return entry


_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "hashed_password", "content", "text"}


def _sanitize_details(details: dict) -> dict:
    """Remove keys that might contain sensitive data from audit details."""
    sanitized = {}
    for key, value in details.items():
        if key.lower() in _SENSITIVE_KEYS:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_details(value)
        else:
            sanitized[key] = value
    return sanitized
