"""Spawn tool for creating background subagents."""

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        workflow_id=StringSchema("Optional workflow id for long-running resumable tasks"),
        stage=StringSchema("Optional workflow stage name for resumable tasks"),
        required=["task"],
    )
)
class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(
        self,
        manager: "SubagentManager",
        can_spawn: Callable[..., Awaitable[str | None]] | None = None,
        on_spawn: Callable[..., Awaitable[None]] | None = None,
    ):
        self._manager = manager
        self._origin_channel: ContextVar[str] = ContextVar("spawn_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("spawn_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("spawn_session_key", default="cli:direct")
        self._can_spawn = can_spawn
        self._on_spawn = on_spawn

    def set_context(self, channel: str, chat_id: str, effective_key: str | None = None) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel.set(channel)
        self._origin_chat_id.set(chat_id)
        self._session_key.set(effective_key or f"{channel}:{chat_id}")

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "For long-running resumable workflows, pass workflow_id and stage. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    async def execute(
        self,
        task: str,
        label: str | None = None,
        workflow_id: str | None = None,
        stage: str | None = None,
        **kwargs: Any
    ) -> str:
        """Spawn a subagent to execute the given task."""
        if self._can_spawn is not None:
            blocked = await self._can_spawn(
                label=label,
                session_key=self._session_key.get(),
                workflow_id=workflow_id,
                stage=stage,
            )
            if blocked:
                return blocked
        task_id, message = await self._manager.spawn_task(
            task=task,
            label=label,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            workflow_id=workflow_id,
            stage=stage,
        )
        if self._on_spawn is not None:
            await self._on_spawn(
                task_id=task_id,
                label=label,
                session_key=self._session_key.get(),
                workflow_id=workflow_id,
                stage=stage,
            )
        return message
