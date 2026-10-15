"""Authentication, authorization, and tenant isolation.

Security invariants:
  1. Organization ID is resolved from the authenticated user, never from request data.
  2. Document access is checked against the user's role and the document's allowed_roles.
  3. Authorization checks happen BEFORE any document content reaches downstream components.
  4. Fail closed: if authorization cannot be established, access is denied.
  5. No plaintext passwords. JWT tokens are short-lived.

This module provides a DEVELOPMENT authentication mechanism suitable for local
demos. It is NOT a substitute for a production identity provider (OAuth2/OIDC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Document, User

_settings = get_settings()

# ── Password hashing ────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT tokens ───────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, org_id: str, role: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=_settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, _settings.secret_key, algorithm=_settings.algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, _settings.secret_key, algorithms=[_settings.algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    if "sub" not in payload or "org" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token payload"
        )
    return payload


# ── Current-user dependency ──────────────────────────────────────────────


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that resolves the authenticated user from a JWT.

    The user's organization_id and role come from the DATABASE, not the token,
    to prevent client-side tampering.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    payload = decode_token(credentials.credentials)
    user_id = payload["sub"]

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated"
        )
    return user


# ── Role hierarchy ───────────────────────────────────────────────────────

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 10,
    "editor": 20,
    "admin": 30,
}


def role_at_least(user_role: str, required_role: str) -> bool:
    """Check whether user_role meets or exceeds the required_role level."""
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 999)


def require_role(user: User, required_role: str) -> None:
    """Raise 403 if the user's role is below the required level."""
    if not role_at_least(user.role, required_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{required_role}' or higher required",
        )


# ── Document-level authorization ─────────────────────────────────────────


def check_document_access(user: User, document: Document) -> bool:
    """Determine whether a user is authorized to access a specific document.

    Authorization rules:
      1. The document must belong to the user's organization (tenant isolation).
      2. The user's role must appear in the document's allowed_roles list,
         OR the user must be an admin.
    """
    # Tenant isolation — hard boundary
    if document.organization_id != user.organization_id:
        return False

    # Admin role bypasses role-based document restrictions within their org
    if user.role == "admin":
        return True

    # Check role-based access
    allowed = document.allowed_roles
    return isinstance(allowed, list) and user.role in allowed


def authorize_evidence(
    user: User,
    documents: dict[str, Document],
    candidate_doc_ids: list[str],
) -> set[str]:
    """Filter a set of candidate document IDs to only those the user may access.

    Returns the set of authorized document IDs. Unauthorized candidates are
    silently discarded — their content must never reach downstream components.
    """
    authorized = set()
    for doc_id in candidate_doc_ids:
        doc = documents.get(doc_id)
        if doc is not None and check_document_access(user, doc):
            authorized.add(doc_id)
    return authorized
