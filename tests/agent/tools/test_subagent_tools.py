"""Tests for subagent tool registration and wiring."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_subagent_exec_tool_receives_allowed_env_keys(tmp_path):
    """allowed_env_keys from ExecToolConfig must be forwarded to the subagent's ExecTool."""
    from nanobot.agent.subagent import SubagentManager, SubagentStatus
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ExecToolConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        exec_config=ExecToolConfig(allowed_env_keys=["GOPATH", "JAVA_HOME"]),
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        exec_tool = spec.tools.get("exec")
        assert exec_tool is not None
        assert exec_tool.allowed_env_keys == ["GOPATH", "JAVA_HOME"]
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


def test_subagent_extracts_structured_hitl_outcome():
    """Structured JSON should be extracted from fenced final text."""
    from nanobot.agent.subagent import SubagentManager

    outcome = SubagentManager._extract_structured_outcome(
        """
```json
{
  "status": "needs_user_input",
  "question": "请补充网格尺寸",
  "resume_payload": {
    "task_template": "继续执行 mesh"
  }
}
```
"""
    )

    assert outcome is not None
    assert outcome["status"] == "needs_user_input"
    assert outcome["question"] == "请补充网格尺寸"


@pytest.mark.asyncio
async def test_spawn_tool_forwards_workflow_context():
    """Spawn tool should forward workflow_id and stage to the manager."""
    from nanobot.agent.tools.spawn import SpawnTool

    manager = MagicMock()
    manager.spawn_task = AsyncMock(return_value=("sub-1", "started"))
    on_spawn = AsyncMock()
    tool = SpawnTool(manager=manager, on_spawn=on_spawn)
    tool.set_context("feishu", "chat123")

    result = await tool.execute(
        task="run mesh stage",
        label="mesh",
        workflow_id="wf_test_1",
        stage="mesh",
    )

    assert result == "started"
    manager.spawn_task.assert_awaited_once_with(
        task="run mesh stage",
        label="mesh",
        origin_channel="feishu",
        origin_chat_id="chat123",
        session_key="feishu:chat123",
        workflow_id="wf_test_1",
        stage="mesh",
    )
    on_spawn.assert_awaited_once_with(
        task_id="sub-1",
        label="mesh",
        session_key="feishu:chat123",
        workflow_id="wf_test_1",
        stage="mesh",
    )
