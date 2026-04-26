"""File-backed workflow store."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.utils.helpers import ensure_dir

from .schema import WorkflowRecord


class WorkflowStore:
    """Persist workflows as JSON files under the workspace."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workflows_dir = ensure_dir(self.workspace / "workflows")

    def _path(self, workflow_id: str) -> Path:
        return self.workflows_dir / f"{workflow_id}.json"

    def create(
        self,
        session_key: str,
        *,
        workflow_type: str = "generic",
        workflow_id: str | None = None,
        current_stage: str | None = None,
    ) -> WorkflowRecord:
        workflow = WorkflowRecord.create(
            session_key,
            workflow_type=workflow_type,
            workflow_id=workflow_id,
            current_stage=current_stage,
        )
        self.save(workflow)
        return workflow

    def load(self, workflow_id: str) -> WorkflowRecord | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return WorkflowRecord.from_dict(data)

    def save(self, workflow: WorkflowRecord) -> None:
        workflow.touch()
        with open(self._path(workflow.workflow_id), "w", encoding="utf-8") as f:
            json.dump(workflow.to_dict(), f, ensure_ascii=False, indent=2)
