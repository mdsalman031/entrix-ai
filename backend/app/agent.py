"""Controlled agentic orchestrator — permission-checked action execution.

Supports a predefined set of mock enterprise actions (create_task, get_task_status,
update_task). Actions are:
  1. Parsed from user requests.
  2. Validated against an explicit allowlist and Pydantic schemas.
  3. Authorized against the user's role and tenant.
  4. Revalidated immediately before execution.
  5. Executed through a controlled mock adapter.
  6. Audited with full provenance.

Security constraints:
  - No arbitrary shell commands, SQL, or HTTP requests.
  - The LLM may propose an action, but the backend enforces permissions.
  - Idempotency keys prevent duplicate execution.
  - TOCTOU protection: policy version is checked at execution time.
  - Evidence sufficient to answer a question does NOT automatically grant
    permission to perform an action.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditEventType, record_audit_event
from app.models import ActionExecution, User
from app.schemas import ActionResponse, ActionStatus
from app.security import role_at_least

logger = structlog.get_logger(__name__)


# ── Action parameter schemas ─────────────────────────────────────────────


class StrictActionParams(BaseModel):
    model_config = {"extra": "forbid"}


class CreateTaskParams(StrictActionParams):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")


class GetTaskStatusParams(StrictActionParams):
    task_id: str = Field(..., min_length=1, max_length=100)


class UpdateTaskParams(StrictActionParams):
    task_id: str = Field(..., min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern=r"^(open|in_progress|resolved|closed)$")
    priority: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")

    def model_post_init(self, __context: Any) -> None:
        if all(
            getattr(self, field) is None for field in ("title", "description", "status", "priority")
        ):
            raise ValueError("At least one mutable task field is required")


# ── Action registry ─────────────────────────────────────────────────────

_ACTION_REGISTRY: dict[str, dict[str, Any]] = {
    "create_task": {
        "description": "Create a new task in the task management system",
        "schema": CreateTaskParams,
        "required_role": "editor",
        "idempotent": False,
    },
    "get_task_status": {
        "description": "Retrieve the current status of a task",
        "schema": GetTaskStatusParams,
        "required_role": "viewer",
        "idempotent": True,
    },
    "update_task": {
        "description": "Update fields of an existing task",
        "schema": UpdateTaskParams,
        "required_role": "editor",
        "idempotent": True,
    },
}


# ── Mock task store ──────────────────────────────────────────────────────

_mock_tasks: dict[str, dict] = {}
_CURRENT_POLICY_VERSION = 1


# ── Action executor ─────────────────────────────────────────────────────


async def execute_action(
    db: AsyncSession,
    user: User,
    action_name: str,
    parameters: dict,
    idempotency_key: str | None = None,
) -> ActionResponse:
    """Execute a controlled enterprise action with full authorization.

    Workflow:
      1. Validate action name against allowlist.
      2. Validate parameters against Pydantic schema.
      3. Check idempotency (prevent duplicate execution).
      4. Authorize: user role >= action required_role, same tenant.
      5. Revalidate authorization at execution time (TOCTOU protection).
      6. Execute through mock adapter.
      7. Record full audit trail.
    """
    correlation_id = str(uuid.uuid4())

    # Step 1: Validate action name
    action_def = _ACTION_REGISTRY.get(action_name)
    if action_def is None:
        await record_audit_event(
            db,
            AuditEventType.ACTION_REJECTED,
            user_id=user.id,
            organization_id=user.organization_id,
            details={"action": action_name, "reason": "unknown_action"},
            correlation_id=correlation_id,
        )
        return ActionResponse(
            execution_id="",
            action_name=action_name,
            status=ActionStatus.REJECTED,
            error_message=f"Unknown action: {action_name}",
            correlation_id=correlation_id,
        )

    # Step 2: Validate parameters
    try:
        validated_params = action_def["schema"](**parameters)
    except ValidationError as e:
        await record_audit_event(
            db,
            AuditEventType.ACTION_REJECTED,
            user_id=user.id,
            organization_id=user.organization_id,
            details={"action": action_name, "reason": "invalid_parameters", "errors": str(e)},
            correlation_id=correlation_id,
        )
        return ActionResponse(
            execution_id="",
            action_name=action_name,
            status=ActionStatus.REJECTED,
            error_message=f"Invalid parameters: {e}",
            correlation_id=correlation_id,
        )

    # Step 3: Check idempotency
    if idempotency_key:
        existing = await db.execute(
            select(ActionExecution).where(
                ActionExecution.idempotency_key == idempotency_key,
                ActionExecution.user_id == user.id,
                ActionExecution.organization_id == user.organization_id,
            )
        )
        existing_exec = existing.scalar_one_or_none()
        if existing_exec is not None:
            logger.info("idempotent_duplicate", key=idempotency_key, exec_id=existing_exec.id)
            return ActionResponse(
                execution_id=existing_exec.id,
                action_name=existing_exec.action_name,
                status=ActionStatus(existing_exec.status),
                result=existing_exec.result,
                correlation_id=existing_exec.correlation_id,
                policy_version=existing_exec.policy_version,
            )

    # Step 4: Authorize
    required_role = action_def["required_role"]
    if not role_at_least(user.role, required_role):
        await record_audit_event(
            db,
            AuditEventType.ACTION_REJECTED,
            user_id=user.id,
            organization_id=user.organization_id,
            details={
                "action": action_name,
                "reason": "insufficient_role",
                "user_role": user.role,
                "required_role": required_role,
            },
            correlation_id=correlation_id,
        )
        return ActionResponse(
            execution_id="",
            action_name=action_name,
            status=ActionStatus.REJECTED,
            error_message=f"Insufficient permissions. Role '{required_role}' or higher required.",
            correlation_id=correlation_id,
        )

    # Create execution record (proposed state)
    execution = ActionExecution(
        user_id=user.id,
        organization_id=user.organization_id,
        action_name=action_name,
        parameters=validated_params.model_dump(),
        status="proposed",
        policy_version=user.action_policy_version,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    db.add(execution)
    await db.flush()

    await record_audit_event(
        db,
        AuditEventType.ACTION_PROPOSED,
        user_id=user.id,
        organization_id=user.organization_id,
        resource_type="action",
        resource_id=execution.id,
        details={"action": action_name, "policy_version": user.action_policy_version},
        correlation_id=correlation_id,
    )

    # Step 5: Revalidate authorization at execution time (TOCTOU)
    refreshed_user = await db.get(User, user.id)
    if (
        refreshed_user is None
        or not refreshed_user.is_active
        or refreshed_user.organization_id != user.organization_id
        or refreshed_user.action_policy_version != execution.policy_version
        or not role_at_least(refreshed_user.role, required_role)
    ):
        execution.status = "rejected"
        execution.error_message = "Authorization changed between proposal and execution"
        await record_audit_event(
            db,
            AuditEventType.ACTION_STALE_POLICY,
            user_id=user.id,
            organization_id=user.organization_id,
            resource_id=execution.id,
            details={"action": action_name, "reason": "stale_authorization"},
            correlation_id=correlation_id,
        )
        return ActionResponse(
            execution_id=execution.id,
            action_name=action_name,
            status=ActionStatus.REJECTED,
            error_message="Authorization context became stale",
            correlation_id=correlation_id,
            policy_version=execution.policy_version,
        )

    # Mark as authorized
    execution.status = "authorized"
    await record_audit_event(
        db,
        AuditEventType.ACTION_AUTHORIZED,
        user_id=user.id,
        organization_id=user.organization_id,
        resource_id=execution.id,
        details={"action": action_name},
        correlation_id=correlation_id,
    )

    # Step 6: Execute through mock adapter
    try:
        result = _execute_mock_action(
            action_name, validated_params.model_dump(), user.organization_id
        )
        execution.status = "executed"
        execution.result = result
        execution.executed_at = datetime.now(UTC)

        await record_audit_event(
            db,
            AuditEventType.ACTION_EXECUTED,
            user_id=user.id,
            organization_id=user.organization_id,
            resource_type="action",
            resource_id=execution.id,
            details={"action": action_name, "result_keys": list(result.keys())},
            correlation_id=correlation_id,
        )

        return ActionResponse(
            execution_id=execution.id,
            action_name=action_name,
            status=ActionStatus.EXECUTED,
            result=result,
            correlation_id=correlation_id,
            policy_version=execution.policy_version,
        )

    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)

        await record_audit_event(
            db,
            AuditEventType.ACTION_FAILED,
            user_id=user.id,
            organization_id=user.organization_id,
            resource_id=execution.id,
            details={"action": action_name, "error": str(e)},
            correlation_id=correlation_id,
        )

        return ActionResponse(
            execution_id=execution.id,
            action_name=action_name,
            status=ActionStatus.FAILED,
            error_message=f"Action execution failed: {e}",
            correlation_id=correlation_id,
            policy_version=execution.policy_version,
        )


# ── Mock action implementations ─────────────────────────────────────────


def _execute_mock_action(action_name: str, params: dict, org_id: str) -> dict:
    """Execute a mock enterprise action. Tenant-scoped to org_id."""
    if action_name == "create_task":
        task_id = f"TASK-{len(_mock_tasks) + 1:04d}"
        task = {
            "task_id": task_id,
            "title": params["title"],
            "description": params.get("description", ""),
            "priority": params.get("priority", "medium"),
            "status": "open",
            "organization_id": org_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        _mock_tasks[f"{org_id}:{task_id}"] = task
        return {"task_id": task_id, "status": "created", "message": f"Task {task_id} created"}

    elif action_name == "get_task_status":
        task_key = f"{org_id}:{params['task_id']}"
        task = _mock_tasks.get(task_key)
        if task is None:
            raise ValueError(f"Task {params['task_id']} not found in your organization")
        return {"task_id": params["task_id"], "status": task["status"], "title": task["title"]}

    elif action_name == "update_task":
        task_key = f"{org_id}:{params['task_id']}"
        task = _mock_tasks.get(task_key)
        if task is None:
            raise ValueError(f"Task {params['task_id']} not found in your organization")
        for field in ["title", "description", "status", "priority"]:
            if params.get(field) is not None:
                task[field] = params[field]
        return {"task_id": params["task_id"], "status": "updated", "current_status": task["status"]}

    raise ValueError(f"Unknown action: {action_name}")


def get_available_actions() -> list[dict]:
    """Return the list of available actions for API documentation."""
    return [
        {
            "name": name,
            "description": defn["description"],
            "required_role": defn["required_role"],
            "parameters": {
                k: str(v.annotation) if hasattr(v, "annotation") else "string"
                for k, v in defn["schema"].model_fields.items()
            },
        }
        for name, defn in _ACTION_REGISTRY.items()
    ]
