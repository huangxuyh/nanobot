from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _make_loop(tmp_path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")


@pytest.mark.asyncio
async def test_subagent_human_request_blocks_workflow(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    result = await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="feishu:c1",
            content="ignored",
            metadata={
                "subagent_outcome": {
                    "status": "needs_user_input",
                    "workflow_id": "wf_mesh_1",
                    "stage": "mesh",
                    "question": "Please provide mesh size.",
                    "fields": [
                        {"name": "element_size", "label": "Mesh Size", "required": True},
                    ],
                    "resume_payload": {
                        "subagent_label": "mesh",
                        "task_template": "Continue mesh stage",
                    },
                },
                "subagent_label": "mesh",
                "subagent_task_id": "sub-1",
            },
        )
    )

    assert result is not None
    assert "Please provide mesh size." in result.content

    workflow = loop.workflows.load("wf_mesh_1")
    assert workflow is not None
    assert workflow.state == "awaiting_user_input"
    assert workflow.current_stage == "mesh"
    assert workflow.awaiting is not None
    assert workflow.awaiting["kind"] == "user_input"
    assert workflow.metadata[AgentLoop._ACTIVE_SUBAGENT_TASK_KEY] == "sub-1"

    session = loop.sessions.get_or_create("feishu:c1")
    assert session.metadata[AgentLoop._ACTIVE_WORKFLOW_KEY] == "wf_mesh_1"
    assert session.messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_user_reply_resumes_blocked_workflow(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop.subagents.spawn_task = AsyncMock(return_value=("sub-2", "started"))  # type: ignore[method-assign]
    loop.subagents.cancel_task = AsyncMock(return_value=False)  # type: ignore[method-assign]

    workflow = loop.workflows.create(
        "feishu:c1",
        workflow_id="wf_mesh_2",
        current_stage="mesh",
    )
    workflow.state = "awaiting_user_input"
    workflow.awaiting = {
        "kind": "user_input",
        "question": "Please provide mesh size.",
        "fields": [{"name": "element_size", "label": "Mesh Size", "required": True}],
    }
    workflow.resume_payload = {
        "subagent_label": "mesh",
        "task_template": "Continue mesh stage",
        "context": {"geometry_path": "workspace/cad/model.step"},
    }
    workflow.metadata[AgentLoop._ACTIVE_SUBAGENT_TASK_KEY] = "sub-1"
    loop.workflows.save(workflow)

    session = loop.sessions.get_or_create("feishu:c1")
    session.metadata[AgentLoop._ACTIVE_WORKFLOW_KEY] = workflow.workflow_id
    loop.sessions.save(session)

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="mesh size 2mm",
        )
    )

    assert result is not None
    assert "Continuing the current workflow" in result.content
    loop.subagents.cancel_task.assert_awaited_once_with("sub-1")
    loop.subagents.spawn_task.assert_awaited_once()
    spawn_kwargs = loop.subagents.spawn_task.await_args.kwargs
    assert spawn_kwargs["workflow_id"] == "wf_mesh_2"
    assert spawn_kwargs["stage"] == "mesh"
    assert "User response:" in spawn_kwargs["task"]
    assert "mesh size 2mm" in spawn_kwargs["task"]

    workflow = loop.workflows.load("wf_mesh_2")
    assert workflow is not None
    assert workflow.state == "resuming"
    assert workflow.awaiting is None
    assert workflow.metadata[AgentLoop._ACTIVE_SUBAGENT_TASK_KEY] == "sub-2"
    assert workflow.metadata["last_user_response"]["raw_text"] == "mesh size 2mm"


@pytest.mark.asyncio
async def test_pending_followup_is_consumed_immediately_after_human_request(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop.subagents.spawn_task = AsyncMock(return_value=("sub-2", "started"))  # type: ignore[method-assign]
    loop.subagents.cancel_task = AsyncMock(return_value=False)  # type: ignore[method-assign]

    pending = asyncio.Queue()
    pending.put_nowait(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="group1_name: first-check;group1_value: alpha",
        )
    )
    loop._pending_queues["feishu:c1"] = pending

    result = await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="feishu:c1",
            content="ignored",
            metadata={
                "subagent_outcome": {
                    "status": "needs_user_input",
                    "workflow_id": "wf_mesh_1",
                    "stage": "mesh",
                    "question": "Please provide mesh size.",
                    "fields": [
                        {"name": "element_size", "label": "Mesh Size", "required": True},
                    ],
                    "resume_payload": {
                        "subagent_label": "mesh",
                        "task_template": "Continue mesh stage",
                    },
                },
                "subagent_label": "mesh",
                "subagent_task_id": "sub-1",
            },
        )
    )

    assert result is not None
    assert "Continuing the current workflow" in result.content
    loop.subagents.cancel_task.assert_awaited_once_with("sub-1")
    loop.subagents.spawn_task.assert_awaited_once()

    workflow = loop.workflows.load("wf_mesh_1")
    assert workflow is not None
    assert workflow.state == "resuming"
    assert workflow.awaiting is None
    assert workflow.metadata["last_user_response"]["raw_text"] == "group1_name: first-check;group1_value: alpha"
    assert pending.empty()


@pytest.mark.asyncio
async def test_approval_reply_must_be_explicit(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop.subagents.spawn_task = AsyncMock(return_value=("sub-2", "started"))  # type: ignore[method-assign]

    workflow = loop.workflows.create(
        "feishu:c1",
        workflow_id="wf_solve_1",
        current_stage="solve",
    )
    workflow.state = "awaiting_approval"
    workflow.awaiting = {
        "kind": "approval",
        "question": "Proceed with solve?",
        "approval_type": "run_solver",
    }
    workflow.resume_payload = {
        "subagent_label": "solve",
        "task_template": "Continue solve stage",
    }
    loop.workflows.save(workflow)

    session = loop.sessions.get_or_create("feishu:c1")
    session.metadata[AgentLoop._ACTIVE_WORKFLOW_KEY] = workflow.workflow_id
    loop.sessions.save(session)

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="maybe later",
        )
    )

    assert result is not None
    assert "waiting for approval" in result.content
    loop.subagents.spawn_task.assert_not_awaited()

    workflow = loop.workflows.load("wf_solve_1")
    assert workflow is not None
    assert workflow.state == "awaiting_approval"


@pytest.mark.asyncio
async def test_user_input_is_blocked_while_workflow_is_resuming(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    workflow = loop.workflows.create(
        "feishu:c1",
        workflow_id="wf_mesh_3",
        current_stage="mesh",
    )
    workflow.state = "resuming"
    workflow.metadata[AgentLoop._ACTIVE_SUBAGENT_TASK_KEY] = "sub-3"
    loop.workflows.save(workflow)

    session = loop.sessions.get_or_create("feishu:c1")
    session.metadata[AgentLoop._ACTIVE_WORKFLOW_KEY] = workflow.workflow_id
    loop.sessions.save(session)

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="duplicate input",
        )
    )

    assert result is not None
    assert "resuming" in result.content


@pytest.mark.asyncio
async def test_stale_active_subagent_is_cleared_before_spawn(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    workflow = loop.workflows.create(
        "feishu:c1",
        workflow_id="wf_mesh_4",
        current_stage="mesh",
    )
    workflow.state = "running"
    workflow.metadata[AgentLoop._ACTIVE_SUBAGENT_TASK_KEY] = "stale-task"
    loop.workflows.save(workflow)

    blocked = await loop._can_spawn_tool_subagent(
        label="mesh",
        session_key="feishu:c1",
        workflow_id="wf_mesh_4",
        stage="mesh",
    )

    assert blocked is None
    workflow = loop.workflows.load("wf_mesh_4")
    assert workflow is not None
    assert AgentLoop._ACTIVE_SUBAGENT_TASK_KEY not in workflow.metadata


def test_system_message_uses_origin_session_key(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    key = loop._effective_session_key(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:direct",
            content="ignored",
        )
    )

    assert key == "cli:direct"
