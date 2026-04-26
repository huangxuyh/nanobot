"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import time
from contextlib import AsyncExitStack, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.autocompact import AutoCompact
from nanobot.agent.context import ContextBuilder
from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.agent.memory import Consolidator, Dream
from nanobot.agent.runner import _MAX_INJECTIONS_PER_TURN, AgentRunner, AgentRunSpec
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.notebook import NotebookEditTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import GlobTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.self import MyTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command import CommandContext, CommandRouter, register_builtin_commands
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.document import extract_documents
from nanobot.utils.helpers import image_placeholder_text
from nanobot.utils.helpers import truncate_text as truncate_text_fn
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE
from nanobot.workflow import WorkflowRecord, WorkflowStore

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, ToolsConfig, WebToolsConfig
    from nanobot.cron.service import CronService


UNIFIED_SESSION_KEY = "unified:default"


class _LoopHook(AgentHook):
    """Core hook for the main loop."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
    ) -> None:
        super().__init__(reraise=True)
        self._loop = agent_loop
        self._on_progress = on_progress
        self._on_stream = on_stream
        self._on_stream_end = on_stream_end
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id
        self._stream_buf = ""

    def wants_streaming(self) -> bool:
        return self._on_stream is not None

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        from nanobot.utils.helpers import strip_think

        prev_clean = strip_think(self._stream_buf)
        self._stream_buf += delta
        new_clean = strip_think(self._stream_buf)
        incremental = new_clean[len(prev_clean) :]
        if incremental and self._on_stream:
            await self._on_stream(incremental)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        if self._on_stream_end:
            await self._on_stream_end(resuming=resuming)
        self._stream_buf = ""

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._loop._current_iteration = context.iteration

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if self._on_progress:
            if not self._on_stream:
                thought = self._loop._strip_think(
                    context.response.content if context.response else None
                )
                if thought:
                    await self._on_progress(thought)
            tool_hint = self._loop._strip_think(self._loop._tool_hint(context.tool_calls))
            await self._on_progress(tool_hint, tool_hint=True)
        for tc in context.tool_calls:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            logger.info("Tool call: {}({})", tc.name, args_str[:200])
        self._loop._set_tool_context(self._channel, self._chat_id, self._message_id)

    async def after_iteration(self, context: AgentHookContext) -> None:
        u = context.usage or {}
        logger.debug(
            "LLM usage: prompt={} completion={} cached={}",
            u.get("prompt_tokens", 0),
            u.get("completion_tokens", 0),
            u.get("cached_tokens", 0),
        )

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return self._loop._strip_think(content)


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
    _PENDING_USER_TURN_KEY = "pending_user_turn"
    _ACTIVE_WORKFLOW_KEY = "active_workflow_id"
    _ACTIVE_SUBAGENT_TASK_KEY = "active_subagent_task_id"
    _ACTIVE_SUBAGENT_LABEL_KEY = "active_subagent_label"
    _PROCESSED_SUBAGENT_TASKS_KEY = "processed_subagent_task_ids"
    _RESUME_GENERATION_KEY = "resume_generation"

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int | None = None,
        context_window_tokens: int | None = None,
        context_block_limit: int | None = None,
        max_tool_result_chars: int | None = None,
        provider_retry_mode: str = "standard",
        web_config: WebToolsConfig | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        timezone: str | None = None,
        session_ttl_minutes: int = 0,
        hooks: list[AgentHook] | None = None,
        unified_session: bool = False,
        disabled_skills: list[str] | None = None,
        tools_config: ToolsConfig | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig, ToolsConfig, WebToolsConfig

        _tc = tools_config or ToolsConfig()
        defaults = AgentDefaults()
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = (
            max_iterations if max_iterations is not None else defaults.max_tool_iterations
        )
        self.context_window_tokens = (
            context_window_tokens
            if context_window_tokens is not None
            else defaults.context_window_tokens
        )
        self.context_block_limit = context_block_limit
        self.max_tool_result_chars = (
            max_tool_result_chars
            if max_tool_result_chars is not None
            else defaults.max_tool_result_chars
        )
        self.provider_retry_mode = provider_retry_mode
        self.web_config = web_config or WebToolsConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self._start_time = time.time()
        self._last_usage: dict[str, int] = {}
        self._extra_hooks: list[AgentHook] = hooks or []

        self.context = ContextBuilder(workspace, timezone=timezone, disabled_skills=disabled_skills)
        self.sessions = session_manager or SessionManager(workspace)
        self.workflows = WorkflowStore(workspace)
        self.tools = ToolRegistry()
        self.runner = AgentRunner(provider)
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            web_config=self.web_config,
            max_tool_result_chars=self.max_tool_result_chars,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            disabled_skills=disabled_skills,
        )
        self._unified_session = unified_session
        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stacks: dict[str, AsyncExitStack] = {}
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Per-session pending queues for mid-turn message injection.
        # When a session has an active task, new messages for that session
        # are routed here instead of creating a new task.
        self._pending_queues: dict[str, asyncio.Queue] = {}
        # NANOBOT_MAX_CONCURRENT_REQUESTS: <=0 means unlimited; default 3.
        _max = int(os.environ.get("NANOBOT_MAX_CONCURRENT_REQUESTS", "3"))
        self._concurrency_gate: asyncio.Semaphore | None = (
            asyncio.Semaphore(_max) if _max > 0 else None
        )
        self.consolidator = Consolidator(
            store=self.context.memory,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=self.context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            max_completion_tokens=provider.generation.max_tokens,
        )
        self.auto_compact = AutoCompact(
            sessions=self.sessions,
            consolidator=self.consolidator,
            session_ttl_minutes=session_ttl_minutes,
        )
        self.dream = Dream(
            store=self.context.memory,
            provider=provider,
            model=self.model,
        )
        self._register_default_tools()
        if _tc.my.enable:
            self.tools.register(MyTool(loop=self, modify_allowed=_tc.my.allow_set))
        self._runtime_vars: dict[str, Any] = {}
        self._current_iteration: int = 0
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = (
            self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
        )
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
        self.tools.register(
            ReadFileTool(
                workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read
            )
        )
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        for cls in (GlobTool, GrepTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(NotebookEditTool(workspace=self.workspace, allowed_dir=allowed_dir))
        if self.exec_config.enable:
            self.tools.register(
                ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                    sandbox=self.exec_config.sandbox,
                    path_append=self.exec_config.path_append,
                    allowed_env_keys=self.exec_config.allowed_env_keys,
                )
            )
        if self.web_config.enable:
            self.tools.register(
                WebSearchTool(config=self.web_config.search, proxy=self.web_config.proxy)
            )
            self.tools.register(WebFetchTool(proxy=self.web_config.proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(
            SpawnTool(
                manager=self.subagents,
                can_spawn=self._can_spawn_tool_subagent,
                on_spawn=self._on_spawn_tool_subagent,
            )
        )
        if self.cron_service:
            self.tools.register(
                CronTool(self.cron_service, default_timezone=self.context.timezone or "UTC")
            )

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stacks = await connect_mcp_servers(self._mcp_servers, self.tools)
            if self._mcp_stacks:
                self._mcp_connected = True
            else:
                logger.warning("No MCP servers connected successfully (will retry next message)")
        except asyncio.CancelledError:
            logger.warning("MCP connection cancelled (will retry next message)")
            self._mcp_stacks.clear()
        except BaseException as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            self._mcp_stacks.clear()
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron", "my"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        from nanobot.utils.helpers import strip_think

        return strip_think(text) or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hints with smart abbreviation."""
        from nanobot.utils.tool_hints import format_tool_hints

        return format_tool_hints(tool_calls)

    def _effective_session_key(self, msg: InboundMessage) -> str:
        """Return the session key used for task routing and mid-turn injections."""
        if self._unified_session and not msg.session_key_override:
            return UNIFIED_SESSION_KEY
        if msg.channel == "system" and not msg.session_key_override:
            return msg.chat_id if ":" in msg.chat_id else f"cli:{msg.chat_id}"
        return msg.session_key

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        session: Session | None = None,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> tuple[str | None, list[str], list[dict], str, bool]:
        """Run the agent iteration loop.

        *on_stream*: called with each content delta during streaming.
        *on_stream_end(resuming)*: called when a streaming session finishes.
        ``resuming=True`` means tool calls follow (spinner should restart);
        ``resuming=False`` means this is the final response.

        Returns (final_content, tools_used, messages, stop_reason, had_injections).
        """
        loop_hook = _LoopHook(
            self,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
        )
        hook: AgentHook = (
            CompositeHook([loop_hook] + self._extra_hooks) if self._extra_hooks else loop_hook
        )

        async def _checkpoint(payload: dict[str, Any]) -> None:
            if session is None:
                return
            self._set_runtime_checkpoint(session, payload)

        async def _drain_pending(*, limit: int = _MAX_INJECTIONS_PER_TURN) -> list[dict[str, Any]]:
            """Non-blocking drain of follow-up messages from the pending queue."""
            if pending_queue is None:
                return []
            if session is not None:
                workflow = self._get_active_workflow(session)
                if (
                    workflow is not None
                    and self._get_active_subagent_task_id(workflow)
                    and workflow.state in {"running", "resuming"}
                ):
                    return []
            items: list[dict[str, Any]] = []
            while len(items) < limit:
                try:
                    pending_msg = pending_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                content = pending_msg.content
                media = pending_msg.media if pending_msg.media else None
                if media:
                    content, media = extract_documents(content, media)
                    media = media or None
                user_content = self.context._build_user_content(content, media)
                runtime_ctx = self.context._build_runtime_context(
                    pending_msg.channel,
                    pending_msg.chat_id,
                    self.context.timezone,
                )
                if isinstance(user_content, str):
                    merged: str | list[dict[str, Any]] = f"{runtime_ctx}\n\n{user_content}"
                else:
                    merged = [{"type": "text", "text": runtime_ctx}] + user_content
                items.append({"role": "user", "content": merged})
            return items

        result = await self.runner.run(AgentRunSpec(
            initial_messages=initial_messages,
            tools=self.tools,
            model=self.model,
            max_iterations=self.max_iterations,
            max_tool_result_chars=self.max_tool_result_chars,
            hook=hook,
            error_message="Sorry, I encountered an error calling the AI model.",
            concurrent_tools=True,
            workspace=self.workspace,
            session_key=session.key if session else None,
            context_window_tokens=self.context_window_tokens,
            context_block_limit=self.context_block_limit,
            provider_retry_mode=self.provider_retry_mode,
            progress_callback=on_progress,
            checkpoint_callback=_checkpoint,
            injection_callback=_drain_pending,
        ))
        self._last_usage = result.usage
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            # Push final content through stream so streaming channels (e.g. Feishu)
            # update the card instead of leaving it empty.
            if on_stream and on_stream_end:
                await on_stream(result.final_content or "")
                await on_stream_end(resuming=False)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return result.final_content, result.tools_used, result.messages, result.stop_reason, result.had_injections

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                self.auto_compact.check_expired(
                    self._schedule_background,
                    active_session_keys=self._pending_queues.keys(),
                )
                continue
            except asyncio.CancelledError:
                # Preserve real task cancellation so shutdown can complete cleanly.
                # Only ignore non-task CancelledError signals that may leak from integrations.
                if not self._running or asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            raw = msg.content.strip()
            if self.commands.is_priority(raw):
                ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=self)
                result = await self.commands.dispatch_priority(ctx)
                if result:
                    await self.bus.publish_outbound(result)
                continue
            effective_key = self._effective_session_key(msg)
            # If this session already has an active pending queue (i.e. a task
            # is processing this session), route the message there for mid-turn
            # injection instead of creating a competing task.
            if effective_key in self._pending_queues:
                pending_msg = msg
                if effective_key != msg.session_key:
                    pending_msg = dataclasses.replace(
                        msg,
                        session_key_override=effective_key,
                    )
                try:
                    self._pending_queues[effective_key].put_nowait(pending_msg)
                except asyncio.QueueFull:
                    logger.warning(
                        "Pending queue full for session {}, falling back to queued task",
                        effective_key,
                    )
                else:
                    logger.info(
                        "Routed follow-up message to pending queue for session {}",
                        effective_key,
                    )
                    continue
            # Compute the effective session key before dispatching
            # This ensures /stop command can find tasks correctly when unified session is enabled
            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.setdefault(effective_key, []).append(task)
            task.add_done_callback(
                lambda t, k=effective_key: self._active_tasks.get(k, [])
                and self._active_tasks[k].remove(t)
                if t in self._active_tasks.get(k, [])
                else None
            )

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message: per-session serial, cross-session concurrent."""
        session_key = self._effective_session_key(msg)
        if session_key != msg.session_key:
            msg = dataclasses.replace(msg, session_key_override=session_key)
        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()

        # Register a pending queue so follow-up messages for this session are
        # routed here (mid-turn injection) instead of spawning a new task.
        pending = asyncio.Queue(maxsize=20)
        self._pending_queues[session_key] = pending

        try:
            async with lock, gate:
                try:
                    on_stream = on_stream_end = None
                    if msg.metadata.get("_wants_stream"):
                        # Split one answer into distinct stream segments.
                        stream_base_id = f"{msg.session_key}:{time.time_ns()}"
                        stream_segment = 0

                        def _current_stream_id() -> str:
                            return f"{stream_base_id}:{stream_segment}"

                        async def on_stream(delta: str) -> None:
                            meta = dict(msg.metadata or {})
                            meta["_stream_delta"] = True
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content=delta,
                                metadata=meta,
                            ))

                        async def on_stream_end(*, resuming: bool = False) -> None:
                            nonlocal stream_segment
                            meta = dict(msg.metadata or {})
                            meta["_stream_end"] = True
                            meta["_resuming"] = resuming
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="",
                                metadata=meta,
                            ))
                            stream_segment += 1

                    response = await self._process_message(
                        msg, on_stream=on_stream, on_stream_end=on_stream_end,
                        pending_queue=pending,
                    )
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content="", metadata=msg.metadata or {},
                        ))
                except asyncio.CancelledError:
                    logger.info("Task cancelled for session {}", session_key)
                    raise
                except Exception:
                    logger.exception("Error processing message for session {}", session_key)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    ))
        finally:
            # Drain any messages still in the pending queue and re-publish
            # them to the bus so they are processed as fresh inbound messages
            # rather than silently lost.
            queue = self._pending_queues.pop(session_key, None)
            if queue is not None:
                leftover = 0
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await self.bus.publish_inbound(item)
                    leftover += 1
                if leftover:
                    logger.info(
                        "Re-published {} leftover message(s) to bus for session {}",
                        leftover, session_key,
                    )

    async def close_mcp(self) -> None:
        """Drain pending background archives, then close MCP connections."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        for name, stack in self._mcp_stacks.items():
            try:
                await stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                logger.debug("MCP server '{}' cleanup error (can be ignored)", name)
        self._mcp_stacks.clear()

    def _schedule_background(self, coro) -> None:
        """Schedule a coroutine as a tracked background task (drained on shutdown)."""
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            if self._restore_runtime_checkpoint(session):
                self.sessions.save(session)
            if self._restore_pending_user_turn(session):
                self.sessions.save(session)

            session, pending = self.auto_compact.prepare_session(session, key)
            if msg.sender_id == "subagent":
                direct = await self._handle_structured_subagent_outcome(
                    session,
                    channel=channel,
                    chat_id=chat_id,
                    metadata=msg.metadata,
                )
                if direct is not None:
                    return direct

            await self.consolidator.maybe_consolidate_by_tokens(session)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=0)
            current_role = "assistant" if msg.sender_id == "subagent" else "user"

            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                session_summary=pending,
                current_role=current_role,
            )
            final_content, tools_used, all_msgs, _, _ = await self._run_agent_loop(
                messages, session=session, channel=channel, chat_id=chat_id,
                message_id=msg.metadata.get("message_id"),
            )
            active_workflow = self._get_active_workflow(session)
            if (
                active_workflow is not None
                and "spawn" in tools_used
                and active_workflow.state == "running"
                and self._get_active_subagent_task_id(active_workflow)
            ):
                final_content = (
                    "Subagent started. Wait for the subagent to return its next status update "
                    "before providing more input."
                )
            self._save_turn(session, all_msgs, 1 + len(history))
            self._clear_runtime_checkpoint(session)
            self.sessions.save(session)
            self._schedule_background(self.consolidator.maybe_consolidate_by_tokens(session))
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        # Extract document text from media at the processing boundary so all
        # channels benefit without format-specific logic in ContextBuilder.
        if msg.media:
            new_content, image_only = extract_documents(msg.content, msg.media)
            msg = dataclasses.replace(msg, content=new_content, media=image_only)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)
        if self._restore_runtime_checkpoint(session):
            self.sessions.save(session)
        if self._restore_pending_user_turn(session):
            self.sessions.save(session)

        session, pending = self.auto_compact.prepare_session(session, key)

        # Slash commands
        raw = msg.content.strip()
        ctx = CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)
        if result := await self.commands.dispatch(ctx):
            return result

        workflow = self._get_active_workflow(session)
        if workflow and workflow.state in {"awaiting_user_input", "awaiting_approval"}:
            return await self._resume_blocked_workflow(session, msg, workflow)
        if workflow and workflow.state == "resuming":
            content = (
                "The current workflow is resuming. "
                "Wait for the active subagent to finish before sending more input."
            )
            session.add_message("user", msg.content)
            session.add_message("assistant", content)
            self.sessions.save(session)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)

        await self.consolidator.maybe_consolidate_by_tokens(session)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=0)

        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            session_summary=pending,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        # Persist the triggering user message immediately, before running the
        # agent loop. If the process is killed mid-turn (OOM, SIGKILL, self-
        # restart, etc.), the existing runtime_checkpoint preserves the
        # in-flight assistant/tool state but NOT the user message itself, so
        # the user's prompt is silently lost on recovery. Saving it up front
        # makes recovery possible from the session log alone.
        user_persisted_early = False
        if isinstance(msg.content, str) and msg.content.strip():
            session.add_message("user", msg.content)
            self._mark_pending_user_turn(session)
            self.sessions.save(session)
            user_persisted_early = True

        final_content, tools_used, all_msgs, stop_reason, had_injections = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            session=session,
            channel=msg.channel,
            chat_id=msg.chat_id,
            message_id=msg.metadata.get("message_id"),
            pending_queue=pending_queue,
        )

        if final_content is None or not final_content.strip():
            final_content = EMPTY_FINAL_RESPONSE_MESSAGE

        active_workflow = self._get_active_workflow(session)
        if (
            active_workflow is not None
            and "spawn" in tools_used
            and active_workflow.state == "running"
            and self._get_active_subagent_task_id(active_workflow)
        ):
            final_content = (
                "Subagent started. Wait for the subagent to return its next status update "
                "before providing more input."
            )

        # Skip the already-persisted user message when saving the turn
        save_skip = 1 + len(history) + (1 if user_persisted_early else 0)
        self._save_turn(session, all_msgs, save_skip)
        self._clear_pending_user_turn(session)
        self._clear_runtime_checkpoint(session)
        self.sessions.save(session)
        self._schedule_background(self.consolidator.maybe_consolidate_by_tokens(session))

        # When follow-up messages were injected mid-turn, a later natural
        # language reply may address those follow-ups and should not be
        # suppressed just because MessageTool was used earlier in the turn.
        # However, if the turn falls back to the empty-final-response
        # placeholder, suppress it when the real user-visible output already
        # came from MessageTool.
        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            if not had_injections or stop_reason == "empty_final_response":
                return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        meta = dict(msg.metadata or {})
        if on_stream is not None and stop_reason != "error":
            meta["_streamed"] = True
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=meta,
        )

    def _sanitize_persisted_blocks(
        self,
        content: list[dict[str, Any]],
        *,
        should_truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """Strip volatile multimodal payloads before writing session history."""
        filtered: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                filtered.append(block)
                continue

            if (
                drop_runtime
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
            ):
                continue

            if block.get("type") == "image_url" and block.get("image_url", {}).get(
                "url", ""
            ).startswith("data:image/"):
                path = (block.get("_meta") or {}).get("path", "")
                filtered.append({"type": "text", "text": image_placeholder_text(path)})
                continue

            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if should_truncate_text and len(text) > self.max_tool_result_chars:
                    text = truncate_text_fn(text, self.max_tool_result_chars)
                filtered.append({**block, "text": text})
                continue

            filtered.append(block)

        return filtered

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime

        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool":
                if isinstance(content, str) and len(content) > self.max_tool_result_chars:
                    entry["content"] = truncate_text_fn(content, self.max_tool_result_chars)
                elif isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, should_truncate_text=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the entire runtime-context block (including any session summary).
                    # The block is bounded by _RUNTIME_CONTEXT_TAG and _RUNTIME_CONTEXT_END.
                    end_marker = ContextBuilder._RUNTIME_CONTEXT_END
                    end_pos = content.find(end_marker)
                    if end_pos >= 0:
                        after = content[end_pos + len(end_marker):].lstrip("\n")
                        if after:
                            entry["content"] = after
                        else:
                            continue
                    else:
                        # Fallback: no end marker found, strip the tag prefix
                        after_tag = content[len(ContextBuilder._RUNTIME_CONTEXT_TAG):].lstrip("\n")
                        if after_tag.strip():
                            entry["content"] = after_tag
                        else:
                            continue
                if isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    def _set_runtime_checkpoint(self, session: Session, payload: dict[str, Any]) -> None:
        """Persist the latest in-flight turn state into session metadata."""
        session.metadata[self._RUNTIME_CHECKPOINT_KEY] = payload
        self.sessions.save(session)

    def _mark_pending_user_turn(self, session: Session) -> None:
        session.metadata[self._PENDING_USER_TURN_KEY] = True

    def _clear_pending_user_turn(self, session: Session) -> None:
        session.metadata.pop(self._PENDING_USER_TURN_KEY, None)

    def _clear_runtime_checkpoint(self, session: Session) -> None:
        if self._RUNTIME_CHECKPOINT_KEY in session.metadata:
            session.metadata.pop(self._RUNTIME_CHECKPOINT_KEY, None)

    def _set_active_workflow(self, session: Session, workflow_id: str) -> None:
        session.metadata[self._ACTIVE_WORKFLOW_KEY] = workflow_id

    def _clear_active_workflow(
        self,
        session: Session,
        *,
        expected_workflow_id: str | None = None,
    ) -> None:
        current = session.metadata.get(self._ACTIVE_WORKFLOW_KEY)
        if expected_workflow_id and current != expected_workflow_id:
            return
        session.metadata.pop(self._ACTIVE_WORKFLOW_KEY, None)

    def _get_active_workflow(self, session: Session) -> WorkflowRecord | None:
        workflow_id = session.metadata.get(self._ACTIVE_WORKFLOW_KEY)
        if not workflow_id:
            return None
        workflow = self.workflows.load(str(workflow_id))
        if workflow is None:
            self._clear_active_workflow(session)
        return workflow

    def _ensure_workflow(
        self,
        session: Session,
        *,
        workflow_id: str | None = None,
        stage: str | None = None,
        workflow_type: str = "generic",
    ) -> WorkflowRecord:
        workflow: WorkflowRecord | None = None
        if workflow_id:
            workflow = self.workflows.load(workflow_id)
            if workflow is None:
                workflow = self.workflows.create(
                    session.key,
                    workflow_type=workflow_type,
                    workflow_id=workflow_id,
                    current_stage=stage,
                )
        else:
            workflow = self._get_active_workflow(session)
        if workflow is None:
            workflow = self.workflows.create(
                session.key,
                workflow_type=workflow_type,
                current_stage=stage,
            )
        if stage:
            workflow.current_stage = stage
        self._set_active_workflow(session, workflow.workflow_id)
        return workflow

    def _get_active_subagent_task_id(self, workflow: WorkflowRecord) -> str | None:
        task_id = workflow.metadata.get(self._ACTIVE_SUBAGENT_TASK_KEY)
        return str(task_id) if task_id else None

    def _set_active_subagent(
        self,
        workflow: WorkflowRecord,
        *,
        task_id: str,
        label: str | None = None,
    ) -> None:
        workflow.metadata[self._ACTIVE_SUBAGENT_TASK_KEY] = task_id
        if label:
            workflow.metadata[self._ACTIVE_SUBAGENT_LABEL_KEY] = label

    def _clear_active_subagent(self, workflow: WorkflowRecord) -> None:
        workflow.metadata.pop(self._ACTIVE_SUBAGENT_TASK_KEY, None)
        workflow.metadata.pop(self._ACTIVE_SUBAGENT_LABEL_KEY, None)

    def _processed_subagent_task_ids(self, workflow: WorkflowRecord) -> set[str]:
        values = workflow.metadata.get(self._PROCESSED_SUBAGENT_TASKS_KEY) or []
        if not isinstance(values, list):
            return set()
        return {str(v) for v in values if v}

    def _mark_subagent_task_processed(self, workflow: WorkflowRecord, task_id: str | None) -> None:
        if not task_id:
            return
        processed = self._processed_subagent_task_ids(workflow)
        processed.add(task_id)
        workflow.metadata[self._PROCESSED_SUBAGENT_TASKS_KEY] = sorted(processed)

    async def _resume_from_pending_followup_if_available(
        self,
        session: Session,
        workflow: WorkflowRecord,
        *,
        channel: str,
        chat_id: str,
    ) -> OutboundMessage | None:
        pending_queue = self._pending_queues.get(session.key)
        if pending_queue is None:
            return None

        drained: list[InboundMessage] = []
        candidate: InboundMessage | None = None
        while True:
            try:
                item = pending_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if (
                candidate is None
                and isinstance(item, InboundMessage)
                and item.channel != "system"
                and bool(item.content.strip())
                and not self.commands.is_priority(item.content.strip())
            ):
                candidate = item
                continue
            drained.append(item)

        for item in drained:
            pending_queue.put_nowait(item)

        if candidate is None:
            return None

        if candidate.channel != channel or candidate.chat_id != chat_id:
            candidate = dataclasses.replace(candidate, channel=channel, chat_id=chat_id)
        return await self._resume_blocked_workflow(session, candidate, workflow)

    def _next_resume_generation(self, workflow: WorkflowRecord) -> int:
        current = workflow.metadata.get(self._RESUME_GENERATION_KEY)
        generation = int(current) + 1 if isinstance(current, int) else 1
        workflow.metadata[self._RESUME_GENERATION_KEY] = generation
        return generation

    async def _on_spawn_tool_subagent(
        self,
        *,
        task_id: str,
        label: str | None,
        session_key: str,
        workflow_id: str | None,
        stage: str | None,
    ) -> None:
        if not workflow_id:
            return
        session = self.sessions.get_or_create(session_key)
        workflow = self._ensure_workflow(
            session,
            workflow_id=workflow_id,
            stage=stage,
        )
        workflow.state = "running"
        self._set_active_subagent(workflow, task_id=task_id, label=label)
        self.workflows.save(workflow)
        self.sessions.save(session)

    async def _can_spawn_tool_subagent(
        self,
        *,
        label: str | None,
        session_key: str,
        workflow_id: str | None,
        stage: str | None,
    ) -> str | None:
        if not workflow_id:
            return None
        session = self.sessions.get_or_create(session_key)
        workflow = self.workflows.load(workflow_id)
        if workflow is None:
            return None
        active_task_id = self._get_active_subagent_task_id(workflow)
        if active_task_id and not self.subagents.is_task_running(active_task_id):
            self._clear_active_subagent(workflow)
            workflow.metadata.pop("last_subagent", None)
            if workflow.state in {"running", "resuming"}:
                workflow.state = "running"
            self.workflows.save(workflow)
            self.sessions.save(session)
            active_task_id = None
        if active_task_id and workflow.state in {"running", "resuming", "awaiting_user_input", "awaiting_approval"}:
            return (
                f"Skipped duplicate subagent spawn for workflow {workflow_id}"
                f" stage {stage or workflow.current_stage or 'unknown'} because an active subagent is already running."
            )
        just_completed_stage = workflow.metadata.get("just_completed_stage")
        if stage and just_completed_stage == stage:
            return (
                f"Skipped duplicate subagent spawn for workflow {workflow_id}"
                f" stage {stage} because this stage was already completed in the current workflow."
            )
        self.sessions.save(session)
        return None

    @staticmethod
    def _format_human_request(outcome: dict[str, Any]) -> str:
        question = str(
            outcome.get("question") or "This workflow needs more information before it can continue."
        ).strip()
        fields = outcome.get("fields")
        if isinstance(fields, list) and fields:
            lines = [question, "", "Please provide the following information:"]
            for field in fields:
                if not isinstance(field, dict):
                    continue
                label = str(field.get("label") or field.get("name") or "Unnamed field")
                required = " (required)" if field.get("required") else ""
                lines.append(f"- {label}{required}")
            return "\n".join(lines)
        if outcome.get("status") == "needs_approval":
            return f'{question}\n\nReply "confirm" to continue, or "cancel" to stop.'
        return question

    @staticmethod
    def _parse_approval_decision(text: str) -> str | None:
        normalized = text.strip().lower()
        if normalized in {
            "\u786e\u8ba4",
            "\u7ee7\u7eed",
            "\u540c\u610f",
            "\u6279\u51c6",
            "confirm",
            "continue",
            "yes",
            "y",
            "approve",
            "approved",
            "ok",
        }:
            return "approve"
        if normalized in {
            "\u53d6\u6d88",
            "\u62d2\u7edd",
            "\u4e0d\u540c\u610f",
            "cancel",
            "no",
            "n",
            "reject",
            "denied",
            "stop",
        }:
            return "reject"
        return None

    def _build_resume_task(
        self,
        workflow: WorkflowRecord,
        user_response: dict[str, Any],
    ) -> str:
        resume_payload = workflow.resume_payload or {}
        task_template = str(
            resume_payload.get("task_template")
            or f"Resume workflow stage {workflow.current_stage or 'unknown'}."
        ).strip()
        sections = [
            task_template,
            "",
            f"Workflow ID: {workflow.workflow_id}",
        ]
        if workflow.current_stage:
            sections.append(f"Stage: {workflow.current_stage}")
        context = resume_payload.get("context")
        if isinstance(context, dict) and context:
            sections.extend([
                "",
                "Saved context:",
                json.dumps(context, ensure_ascii=False, indent=2),
            ])
        sections.extend([
            "",
            "User response:",
            json.dumps(user_response, ensure_ascii=False, indent=2),
            "",
            "Continue from the current stage instead of restarting the whole workflow.",
        ])
        return "\n".join(sections)

    async def _handle_structured_subagent_outcome(
        self,
        session: Session,
        *,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any],
    ) -> OutboundMessage | None:
        outcome = metadata.get("subagent_outcome")
        if not isinstance(outcome, dict):
            return None

        status = str(outcome.get("status") or "")
        stage = outcome.get("stage")
        workflow_id = outcome.get("workflow_id")
        task_id = str(metadata.get("subagent_task_id") or "") or None

        if status in {"needs_user_input", "needs_approval"}:
            workflow = self._ensure_workflow(
                session,
                workflow_id=str(workflow_id) if workflow_id else None,
                stage=str(stage) if stage else None,
                workflow_type=str(outcome.get("workflow_type") or "generic"),
            )
            active_task_id = self._get_active_subagent_task_id(workflow)
            processed_task_ids = self._processed_subagent_task_ids(workflow)
            if task_id in processed_task_ids:
                return OutboundMessage(channel=channel, chat_id=chat_id, content="")
            if active_task_id and task_id and active_task_id != task_id:
                return OutboundMessage(channel=channel, chat_id=chat_id, content="")
            workflow.state = (
                "awaiting_user_input" if status == "needs_user_input" else "awaiting_approval"
            )
            workflow.awaiting = {
                "kind": "user_input" if status == "needs_user_input" else "approval",
                "question": outcome.get("question"),
                "fields": outcome.get("fields") if isinstance(outcome.get("fields"), list) else [],
                "approval_type": outcome.get("approval_type"),
                "blocking": True,
            }
            workflow.resume_payload = (
                dict(outcome.get("resume_payload") or {})
                if isinstance(outcome.get("resume_payload"), dict)
                else {}
            )
            workflow.metadata["last_subagent"] = {
                "task_id": metadata.get("subagent_task_id"),
                "label": metadata.get("subagent_label"),
            }
            if task_id:
                self._set_active_subagent(
                    workflow,
                    task_id=task_id,
                    label=str(metadata.get("subagent_label") or ""),
                )
                self._mark_subagent_task_processed(workflow, task_id)
            self.workflows.save(workflow)
            self.sessions.save(session)

            resumed = await self._resume_from_pending_followup_if_available(
                session,
                workflow,
                channel=channel,
                chat_id=chat_id,
            )
            if resumed is not None:
                return resumed

            content = self._format_human_request(outcome)
            session.add_message("assistant", content)
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id, content=content)

        if status in {"ok", "error"}:
            workflow = None
            if workflow_id or session.metadata.get(self._ACTIVE_WORKFLOW_KEY):
                workflow = self._ensure_workflow(
                    session,
                    workflow_id=str(workflow_id) if workflow_id else None,
                    stage=str(stage) if stage else None,
                    workflow_type=str(outcome.get("workflow_type") or "generic"),
                )
            if workflow is not None:
                active_task_id = self._get_active_subagent_task_id(workflow)
                processed_task_ids = self._processed_subagent_task_ids(workflow)
                if task_id in processed_task_ids:
                    return OutboundMessage(channel=channel, chat_id=chat_id, content="")
                if active_task_id and task_id and active_task_id != task_id:
                    return OutboundMessage(channel=channel, chat_id=chat_id, content="")
                workflow.awaiting = None
                if status == "error":
                    workflow.state = "failed"
                    self._clear_active_subagent(workflow)
                    self._clear_active_workflow(
                        session,
                        expected_workflow_id=workflow.workflow_id,
                    )
                else:
                    workflow.state = "running"
                    self._clear_active_subagent(workflow)
                    if workflow.current_stage:
                        workflow.metadata["just_completed_stage"] = workflow.current_stage
                self._mark_subagent_task_processed(workflow, task_id)
                self.workflows.save(workflow)
                self.sessions.save(session)
        return None

    async def _resume_blocked_workflow(
        self,
        session: Session,
        msg: InboundMessage,
        workflow: WorkflowRecord,
    ) -> OutboundMessage:
        user_text = msg.content.strip()
        awaiting = workflow.awaiting or {}
        response_payload: dict[str, Any]

        if workflow.state == "awaiting_approval":
            decision = self._parse_approval_decision(user_text)
            if decision is None:
                content = 'This workflow is waiting for approval. Reply "confirm" to continue, or "cancel" to stop.'
                session.add_message("user", msg.content)
                session.add_message("assistant", content)
                self.sessions.save(session)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)
            if decision == "reject":
                workflow.state = "cancelled"
                workflow.awaiting = None
                self.workflows.save(workflow)
                self._clear_active_workflow(session, expected_workflow_id=workflow.workflow_id)
                session.add_message("user", msg.content)
                content = "Cancelled the workflow that was waiting for approval."
                session.add_message("assistant", content)
                self.sessions.save(session)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)
            response_payload = {"approval": "approved", "raw_text": user_text}
        else:
            response_payload = {"raw_text": user_text}
            fields = awaiting.get("fields")
            if isinstance(fields, list) and fields:
                response_payload["fields"] = fields
            if msg.media:
                response_payload["media"] = list(msg.media)

        workflow.metadata["last_user_response"] = response_payload
        workflow.state = "resuming"
        workflow.awaiting = None
        workflow.metadata.pop("just_completed_stage", None)
        previous_task_id = self._get_active_subagent_task_id(workflow)
        if previous_task_id:
            await self.subagents.cancel_task(previous_task_id)
            self._mark_subagent_task_processed(workflow, previous_task_id)
        generation = self._next_resume_generation(workflow)
        self.workflows.save(workflow)

        task = self._build_resume_task(workflow, response_payload)
        label = str(
            (workflow.resume_payload or {}).get("subagent_label")
            or workflow.current_stage
            or "workflow-resume"
        )
        task_id, _ = await self.subagents.spawn_task(
            task=task,
            label=label,
            origin_channel=msg.channel,
            origin_chat_id=msg.chat_id,
            session_key=session.key,
            workflow_id=workflow.workflow_id,
            stage=workflow.current_stage,
        )
        self._set_active_subagent(workflow, task_id=task_id, label=label)
        workflow.metadata["resume_generation_active"] = generation
        self.workflows.save(workflow)

        stage_suffix = f" ({workflow.current_stage})" if workflow.current_stage else ""
        content = f"Received your input. Continuing the current workflow{stage_suffix}."
        session.add_message("user", msg.content)
        session.add_message("assistant", content)
        self.sessions.save(session)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)

    @staticmethod
    def _checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
        return (
            message.get("role"),
            message.get("content"),
            message.get("tool_call_id"),
            message.get("name"),
            message.get("tool_calls"),
            message.get("reasoning_content"),
            message.get("thinking_blocks"),
        )

    def _restore_runtime_checkpoint(self, session: Session) -> bool:
        """Materialize an unfinished turn into session history before a new request."""
        from datetime import datetime

        checkpoint = session.metadata.get(self._RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return False

        assistant_message = checkpoint.get("assistant_message")
        completed_tool_results = checkpoint.get("completed_tool_results") or []
        pending_tool_calls = checkpoint.get("pending_tool_calls") or []

        restored_messages: list[dict[str, Any]] = []
        if isinstance(assistant_message, dict):
            restored = dict(assistant_message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
        for message in completed_tool_results:
            if isinstance(message, dict):
                restored = dict(message)
                restored.setdefault("timestamp", datetime.now().isoformat())
                restored_messages.append(restored)
        for tool_call in pending_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            name = ((tool_call.get("function") or {}).get("name")) or "tool"
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": "Error: Task interrupted before this tool finished.",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self._checkpoint_message_key(left) == self._checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])

        self._clear_pending_user_turn(session)
        self._clear_runtime_checkpoint(session)
        return True

    def _restore_pending_user_turn(self, session: Session) -> bool:
        """Close a turn that only persisted the user message before crashing."""
        from datetime import datetime

        if not session.metadata.get(self._PENDING_USER_TURN_KEY):
            return False

        if session.messages and session.messages[-1].get("role") == "user":
            session.messages.append(
                {
                    "role": "assistant",
                    "content": "Error: Task interrupted before a response was generated.",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            session.updated_at = datetime.now()

        self._clear_pending_user_turn(session)
        return True

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        media: list[str] | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a message directly and return the outbound payload."""
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id,
            content=content, media=media or [],
        )
        return await self._process_message(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )
