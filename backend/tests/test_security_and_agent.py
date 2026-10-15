from __future__ import annotations

import pytest

from app.agent import _mock_tasks, execute_action
from app.ingestion import ingest_document
from app.models import Organization, User
from app.retrieval import RetrievalEngine
from app.schemas import ActionStatus
from app.security import hash_password


async def create_user(db, organization: Organization, username: str, role: str) -> User:
    user = User(
        organization_id=organization.id,
        username=username,
        email=f"{username}@example.test",
        role=role,
        hashed_password=hash_password("password"),
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_retrieval_never_exposes_other_tenant_or_role_restricted_text(db):
    acme = Organization(name="Acme", slug="acme")
    globex = Organization(name="Globex", slug="globex")
    db.add_all([acme, globex])
    await db.flush()
    viewer = await create_user(db, acme, "viewer", "viewer")
    globex_editor = await create_user(db, globex, "globex-editor", "editor")
    engine = RetrievalEngine()
    restricted = await ingest_document(
        db,
        engine,
        organization_id=acme.id,
        title="Admin forecast",
        source_id="forecast",
        allowed_roles=["admin"],
        content="RESTRICTED_SENTINEL: Acme forecast is 4.2 million.",
    )
    await ingest_document(
        db,
        engine,
        organization_id=globex.id,
        title="Globex guide",
        source_id="guide",
        allowed_roles=["viewer", "editor", "admin"],
        content="Globex onboarding begins Monday.",
    )
    await db.commit()

    acme_results = await engine.search("forecast 4.2 million", viewer, db)
    cross_tenant_results = await engine.search("Acme forecast", globex_editor, db)

    assert acme_results == []
    assert all(item.document_id != restricted.id for item in cross_tenant_results)
    assert "RESTRICTED_SENTINEL" not in " ".join(
        item.text for item in acme_results + cross_tenant_results
    )


@pytest.mark.asyncio
async def test_actions_reject_unknown_parameters_and_scope_idempotency_to_tenant(db):
    _mock_tasks.clear()
    acme = Organization(name="Acme", slug="acme")
    globex = Organization(name="Globex", slug="globex")
    db.add_all([acme, globex])
    await db.flush()
    acme_editor = await create_user(db, acme, "acme-editor", "editor")
    globex_editor = await create_user(db, globex, "globex-editor", "editor")

    invalid = await execute_action(
        db, acme_editor, "create_task", {"title": "x", "shell": "rm -rf /"}
    )
    assert invalid.status is ActionStatus.REJECTED

    first = await execute_action(
        db, acme_editor, "create_task", {"title": "Acme task"}, "shared-key"
    )
    second = await execute_action(
        db, globex_editor, "create_task", {"title": "Globex task"}, "shared-key"
    )
    assert first.status is ActionStatus.EXECUTED
    assert second.status is ActionStatus.EXECUTED
    assert first.execution_id != second.execution_id

    duplicate = await execute_action(
        db, acme_editor, "create_task", {"title": "ignored"}, "shared-key"
    )
    assert duplicate.execution_id == first.execution_id
