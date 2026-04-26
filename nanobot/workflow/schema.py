"""Workflow state schema for blocking human-in-the-loop flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal
import uuid

WorkflowState = Literal[
    "running",
    "awaiting_user_input",
    "awaiting_approval",
    "resuming",
    "completed",
    "failed",
    "cancelled",
]


def _utcnow_iso() -> str:
    return datetime.now().isoformat()


@dataclass(slots=True)
class WorkflowRecord:
    """Persisted state for a single long-running workflow."""

    workflow_id: str
    session_key: str
    workflow_type: str = "generic"
    state: WorkflowState = "running"
    current_stage: str | None = None
    awaiting: dict[str, Any] | None = None
    resume_payload: dict[str, Any] | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    @classmethod
    def create(
        cls,
        session_key: str,
        *,
        workflow_type: str = "generic",
        workflow_id: str | None = None,
        current_stage: str | None = None,
    ) -> "WorkflowRecord":
        return cls(
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:12]}",
            session_key=session_key,
            workflow_type=workflow_type,
            current_stage=current_stage,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRecord":
        return cls(
            workflow_id=str(data["workflow_id"]),
            session_key=str(data["session_key"]),
            workflow_type=str(data.get("workflow_type") or "generic"),
            state=str(data.get("state") or "running"),
            current_stage=data.get("current_stage"),
            awaiting=data.get("awaiting"),
            resume_payload=data.get("resume_payload"),
            artifacts=dict(data.get("artifacts") or {}),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or _utcnow_iso()),
            updated_at=str(data.get("updated_at") or _utcnow_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()
