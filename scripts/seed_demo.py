"""Seed Entrix AI with synthetic two-tenant demonstration data.

Run from ``backend`` with ``python ../scripts/seed_demo.py``. This script is
idempotent by username/source identifier and never uses production content.
"""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select

from app.database import async_session_factory, init_db
from app.ingestion import ingest_document
from app.models import Organization, User
from app.retrieval import RetrievalEngine
from app.security import hash_password

USERS = (
    ("acme", "Acme Corp", "alice", "alice@acme.example", "admin"),
    ("acme", "Acme Corp", "bob", "bob@acme.example", "editor"),
    ("acme", "Acme Corp", "charlie", "charlie@acme.example", "viewer"),
    ("globex", "Globex Inc", "diana", "diana@globex.example", "admin"),
    ("globex", "Globex Inc", "eve", "eve@globex.example", "editor"),
)

DOCUMENTS = (
    (
        "acme",
        "Security policy",
        "security-policy-v1",
        ["viewer", "editor", "admin"],
        "Synthetic demonstration data. Acme's password policy requires unique passwords of at least 14 characters. Passwords must not be shared and multifactor authentication is required for remote access.",
    ),
    (
        "acme",
        "Incident response",
        "incident-response-v1",
        ["editor", "admin"],
        "Synthetic demonstration data. Acme staff must report a suspected data breach to Security Operations within one hour. The incident lead preserves evidence, assesses impact, and coordinates notification.",
    ),
    (
        "acme",
        "Quarterly forecast",
        "forecast-v1",
        ["admin"],
        "Synthetic demonstration data. The confidential quarterly revenue projection is $4.2 million. This material is restricted to Acme administrators.",
    ),
    (
        "globex",
        "Onboarding guide",
        "onboarding-v1",
        ["viewer", "editor", "admin"],
        "Synthetic demonstration data. Globex onboarding includes account provisioning, a security orientation, and a manager check-in during the first week.",
    ),
)


async def main(if_empty: bool = False) -> None:
    await init_db()
    engine = RetrievalEngine()
    async with async_session_factory() as db:
        existing_users = await db.scalar(select(func.count()).select_from(User))
        if if_empty and existing_users:
            print("Demo database already contains users; seed skipped.")
            return
        organizations: dict[str, Organization] = {}
        for slug, name, username, email, role in USERS:
            organization = organizations.get(slug)
            if organization is None:
                organization = (
                    await db.execute(
                        select(Organization).where(Organization.slug == slug)
                    )
                ).scalar_one_or_none()
                if organization is None:
                    organization = Organization(slug=slug, name=name)
                    db.add(organization)
                    await db.flush()
                organizations[slug] = organization
            user = (
                await db.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()
            if user is None:
                db.add(
                    User(
                        organization_id=organization.id,
                        username=username,
                        email=email,
                        role=role,
                        hashed_password=hash_password("password"),
                    )
                )

        await db.flush()
        for slug, title, source_id, allowed_roles, content in DOCUMENTS:
            await ingest_document(
                db,
                engine,
                organization_id=organizations[slug].id,
                title=title,
                source_id=source_id,
                allowed_roles=allowed_roles,
                content=content,
            )
        await db.commit()
    print(
        "Seeded synthetic Entrix AI demo tenants. Demo password for every user: password"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-empty", action="store_true", help="Seed only when no users exist"
    )
    args = parser.parse_args()
    asyncio.run(main(if_empty=args.if_empty))
