from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CAEGuardrailConfig
from nanobot.providers.base import LLMResponse


def _make_loop(tmp_path, *, guardrail: CAEGuardrailConfig | None = None) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock()
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cae_guardrail_config=guardrail,
    )


@pytest.mark.asyncio
async def test_guardrail_denies_non_cae_request_before_agent_loop(tmp_path) -> None:
    loop = _make_loop(
        tmp_path,
        guardrail=CAEGuardrailConfig(enable=True, mode="rule_only"),
    )
    loop._run_agent_loop = AsyncMock()  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="推荐几部最近的电影",
        )
    )

    assert result is not None
    assert "我只能处理 CAE 相关" in result.content
    loop._run_agent_loop.assert_not_awaited()


@pytest.mark.asyncio
async def test_guardrail_allows_cae_request_to_continue(tmp_path) -> None:
    loop = _make_loop(
        tmp_path,
        guardrail=CAEGuardrailConfig(enable=True, mode="rule_only"),
    )
    loop._run_agent_loop = AsyncMock(return_value=(
        "CAE ok",
        [],
        [
            {"role": "user", "content": "请帮我生成网格脚本"},
            {"role": "assistant", "content": "CAE ok"},
        ],
        "completed",
        False,
    ))  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="请帮我生成网格脚本",
        )
    )

    assert result is not None
    assert result.content == "CAE ok"
    loop._run_agent_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_guardrail_uses_llm_for_gray_request(tmp_path) -> None:
    loop = _make_loop(
        tmp_path,
        guardrail=CAEGuardrailConfig(enable=True, mode="rule_plus_llm"),
    )
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content='{"action":"deny","category":"out_of_scope","confidence":0.98}'
    ))
    loop._run_agent_loop = AsyncMock()  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="c1",
            content="给我推荐一些好电影",
        )
    )

    assert result is not None
    assert "我只能处理 CAE 相关" in result.content
    loop.provider.chat_with_retry.assert_awaited_once()
    loop._run_agent_loop.assert_not_awaited()


@pytest.mark.asyncio
async def test_guardrail_does_not_block_hitl_style_reply(tmp_path) -> None:
    loop = _make_loop(
        tmp_path,
        guardrail=CAEGuardrailConfig(enable=True, mode="rule_only"),
    )
    loop.subagents.spawn_task = AsyncMock(return_value=("sub-2", "started"))  # type: ignore[method-assign]
    loop.subagents.cancel_task = AsyncMock(return_value=False)  # type: ignore[method-assign]

    workflow = loop.workflows.create(
        "feishu:c1",
        workflow_id="wf_mesh_guardrail",
        current_stage="mesh",
    )
    workflow.state = "awaiting_user_input"
    workflow.awaiting = {
        "kind": "user_input",
        "question": "Please provide mesh size.",
        "fields": [{"name": "mesh_size", "label": "Mesh Size", "required": True}],
    }
    workflow.resume_payload = {
        "subagent_label": "mesh",
        "task_template": "Continue mesh stage",
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
            content="mesh_size: 2.0 mm",
        )
    )

    assert result is not None
    assert "Continuing the current workflow" in result.content
    loop.subagents.spawn_task.assert_awaited_once()
