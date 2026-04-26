# Nanobot Agent 架构详解

> 面向二次开发者的 Agent 系统完整教程
> 基于 v0.1.5.post1 源码分析

---

## 目录

1. [架构总览](#一架构总览)
2. [AgentLoop — 核心编排器](#二agentloop--核心编排器)
3. [AgentRunner — 通用 LLM 工具循环](#三agentrunner--通用-llm-工具循环)
4. [ContextBuilder — 上下文构建器](#四contextbuilder--上下文构建器)
5. [记忆系统](#五记忆系统)
6. [技能系统](#六技能系统)
7. [工具系统](#七工具系统)
8. [子 Agent 系统](#八子-agent-系统)
9. [消息总线](#九消息总线)
10. [会话管理](#十会话管理)
11. [命令路由](#十一命令路由)
12. [生命周期钩子](#十二生命周期钩子)
13. [自动压缩](#十三自动压缩)
14. [二次开发指南](#十四二次开发指南)

---

## 一、架构总览

### 1.1 设计哲学

Nanobot Agent 系统的核心设计理念是**关注点分离**：

- **AgentLoop** 负责产品层关注（消息路由、会话管理、流式输出、MCP、子 Agent、自动压缩）
- **AgentRunner** 是纯粹的 LLM 工具调用引擎（调用 LLM → 执行工具 → 重复），不感知任何产品层概念
- 这种分离使得子 Agent、Dream 处理器等可以复用 `AgentRunner`，而无需引入完整的 Agent 栈

### 1.2 整体结构

```
                         +------------------------+
                         |      AgentLoop         |
                         |   (agent/loop.py)      |
                         |     核心编排器          |
                         +-----------+------------+
                                     |
          +--------------------------+--------------------------+
          |            |             |             |            |
          v            v             v             v            v
    +----------+ +-----------+ +----------+ +-----------+ +----------+
    | Context  | |  Agent    | |  Tool    | | Subagent  | | Command  |
    | Builder  | |  Runner   | | Registry | |  Manager  | | Router   |
    +----+-----+ +-----+-----+ +----+-----+ +-----+-----+ +----+-----+
         |            |            |             |            |
         v            v            v             v            v
    +----------+ +-----------+ +----------+ +-----------+ +----------+
    | Memory   | |  Context  | |  Tool    | | Message   | | Built-in |
    | Store    | |  Window   | |  Base    | |   Bus     | | Commands |
    +----+-----+ |  Manager  | +----------+ +-----------+ +----------+
         |       +-----------+
    +----+-----+
    |  GitStore|
    +----------+
```

### 1.3 数据流

```
Chat Platform → Channel → InboundMessage → MessageBus.inbound
                                                    ↓
                                              AgentLoop
                                         (消费消息, 路由到 session)
                                                    ↓
                                        ┌───────────────────┐
                                        │   ContextBuilder   │
                                        │ 组装系统提示词 + 消息 │
                                        └─────────┬─────────┘
                                                  ↓
                                        ┌───────────────────┐
                                        │   AgentRunner      │
                                        │ LLM 调用 ↔ 工具执行 │
                                        │ (循环直到最终回复)   │
                                        └─────────┬─────────┘
                                                  ↓
                                     OutboundMessage → MessageBus.outbound
                                                    ↓
                                              Channel → Chat Platform
```

### 1.4 核心文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `nanobot/agent/loop.py` | ~1000 | AgentLoop：核心编排器 |
| `nanobot/agent/runner.py` | ~990 | AgentRunner：通用 LLM 工具循环 |
| `nanobot/agent/context.py` | ~210 | ContextBuilder：系统提示词组装 |
| `nanobot/agent/memory.py` | ~1200 | MemoryStore + Consolidator + Dream |
| `nanobot/agent/skills.py` | ~200 | SkillsLoader：技能发现和加载 |
| `nanobot/agent/hook.py` | ~105 | AgentHook + CompositeHook |
| `nanobot/agent/autocompact.py` | ~125 | AutoCompact：空闲会话压缩 |
| `nanobot/agent/subagent.py` | ~315 | SubagentManager：后台子 Agent |
| `nanobot/agent/tools/registry.py` | ~125 | ToolRegistry：工具注册和执行 |
| `nanobot/agent/tools/base.py` | ~280 | Tool + Schema：工具基类和 Schema |
| `nanobot/bus/queue.py` | ~30 | MessageBus：消息队列 |
| `nanobot/bus/events.py` | ~30 | InboundMessage / OutboundMessage |
| `nanobot/session/manager.py` | ~200 | SessionManager：会话持久化 |
| `nanobot/command/router.py` | ~100 | CommandRouter：命令路由 |
| `nanobot/command/builtin.py` | ~200 | 内置命令实现 |

---

## 二、AgentLoop — 核心编排器

**文件**：`nanobot/agent/loop.py`

AgentLoop 是整个系统的中枢，它持有所有子系统并将它们串联在一起。

### 2.1 构造函数

```python
class AgentLoop:
    def __init__(
        self,
        bus: MessageBus,                    # 消息总线
        provider: LLMProvider,              # LLM 提供商
        workspace: Path,                    # 工作区路径
        model: str | None = None,           # 模型名称
        max_iterations: int | None = None,  # 最大工具调用轮次
        context_window_tokens: int | None = None,   # 上下文窗口 token 数
        session_ttl_minutes: int = 0,       # 自动压缩超时（0=禁用）
        hooks: list[AgentHook] | None = None,  # 生命周期钩子
        unified_session: bool = False,      # 统一会话模式
        disabled_skills: list[str] | None = None,  # 禁用的技能
        # ... 更多配置
    )
```

构造函数会初始化以下子系统：

| 属性 | 类型 | 用途 |
|------|------|------|
| `self.context` | `ContextBuilder` | 系统提示词和消息列表组装 |
| `self.sessions` | `SessionManager` | 按 session 持久化对话历史 |
| `self.tools` | `ToolRegistry` | 工具注册和执行 |
| `self.runner` | `AgentRunner` | 通用 LLM 工具调用循环 |
| `self.subagents` | `SubagentManager` | 后台子 Agent 执行 |
| `self.consolidator` | `Consolidator` | Token 预算触发的会话摘要 |
| `self.auto_compact` | `AutoCompact` | TTL 触发的空闲会话压缩 |
| `self.dream` | `Dream` | 定时记忆整合 |
| `self.commands` | `CommandRouter` | 斜杠命令分发器 |

### 2.2 并发控制原语

```python
self._active_tasks: dict[str, list[asyncio.Task]]  # session_key → 活动任务列表
self._session_locks: dict[str, asyncio.Lock]       # session_key → 每 session 串行锁
self._pending_queues: dict[str, asyncio.Queue]     # session_key → 待注入消息队列
self._concurrency_gate: asyncio.Semaphore          # 全局并发门控（默认 3）
```

**设计要点**：
- **每 session 串行**：同一 session 的消息通过 `asyncio.Lock` 串行处理，保证对话顺序
- **跨 session 并发**：不同 session 通过 Semaphore 门控并发执行
- **全局并发限制**：通过 `NANOBOT_MAX_CONCURRENT_REQUESTS` 环境变量控制

### 2.3 主事件循环 `run()`

```python
async def run(self) -> None:
    self._running = True
    await self._connect_mcp()
    while self._running:
        try:
            # 1 秒超时消费，超时后触发自动压缩检查
            msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
        except asyncio.TimeoutError:
            self.auto_compact.check_expired(...)  # 检查空闲 session
            continue

        # 优先级命令（如 /stop）直接处理，不创建 Task
        if self.commands.is_priority(raw_text):
            self.commands.dispatch_priority(ctx)
            continue

        # 统一 session 模式：所有消息路由到同一 session key
        effective_key = self._effective_session_key(msg)

        # 如果 session 已有活跃任务，新消息放入待注入队列
        if effective_key in self._pending_queues:
            self._pending_queues[effective_key].put_nowait(pending_msg)
            continue

        # 否则创建新的处理任务
        task = asyncio.create_task(self._dispatch(msg))
```

### 2.4 每消息调度 `_dispatch()`

```python
async def _dispatch(self, msg: InboundMessage) -> None:
    session_key = self._effective_session_key(msg)
    lock = self._session_locks.setdefault(session_key, asyncio.Lock())
    gate = self._concurrency_gate or nullcontext()

    # 为该 session 创建待注入队列
    pending = asyncio.Queue(maxsize=20)
    self._pending_queues[session_key] = pending

    async with lock, gate:
        response = await self._process_message(msg, session_key, ...)
        if response:
            await self.bus.publish_outbound(response)

    # finally：将剩余待注入消息重新发布为新的入站消息
    queue = self._pending_queues.pop(session_key, None)
    while queue:
        item = queue.get_nowait()
        await self.bus.publish_inbound(item)
```

**关键设计**：
- **per-session serial, cross-session concurrent**：同一 session 串行，不同 session 可并发
- **流式分段**：如果请求了流式（`_wants_stream`），输出被分段发送
- **finally 清理**：确保剩余消息不会丢失

### 2.5 核心消息处理 `_process_message()`

处理两条路径：

**路径 A：系统消息**（子 Agent 公告等）
1. 从 `chat_id` 解析来源
2. 获取/创建 session，恢复运行时检查点
3. `auto_compact.prepare_session()` — 加载摘要
4. `consolidator.maybe_consolidate_by_tokens()` — token 预算检查
5. `context.build_messages()` 组装消息（`current_role="assistant"`）
6. 运行 `_run_agent_loop()`，保存回合，清除检查点

**路径 B：普通用户消息**
1. 从媒体中提取文档文本
2. 获取/创建 session，恢复检查点
3. `auto_compact.prepare_session()` — 应用空闲摘要
4. `commands.dispatch()` — 分发斜杠命令
5. `consolidator.maybe_consolidate_by_tokens()` — token 整合
6. **提前持久化用户消息**（防止 OOM/崩溃丢失）
7. `context.build_messages()` 组装完整消息列表
8. `_run_agent_loop()` 带进度/流式回调
9. `_save_turn()` 持久化新消息
10. 调度后台整合

### 2.6 工具注册

`_register_default_tools()` 注册标准工具集：

```python
# 文件工具
read_file, write_file, edit_file, list_dir, glob, grep, notebook_edit
# 执行工具
exec
# Web 工具
web_search, web_fetch
# 消息和调度
message, spawn, cron
# 可选：自我修改
my（如果 tools.my.enable=True）
```

文件工具的 `allowed_dir` 设置为 workspace 目录（沙箱或限制模式）。

---

## 三、AgentRunner — 通用 LLM 工具循环

**文件**：`nanobot/agent/runner.py`

AgentRunner 是纯粹的 LLM 工具调用引擎。它不知道 MessageBus、频道、会话的存在。

### 3.1 数据结构

```python
@dataclass
class AgentRunSpec:
    initial_messages: list[dict]        # 初始消息列表
    tools: ToolRegistry                 # 工具注册表
    model: str | None                   # 模型名称
    max_iterations: int                 # 最大迭代次数
    max_tool_result_chars: int          # 工具结果最大字符数
    hook: AgentHook | None              # 生命周期钩子
    concurrent_tools: bool              # 是否并发执行安全工具
    checkpoint_callback: Callable       # 检查点回调（崩溃恢复）
    injection_callback: Callable        # 待注入消息回调（中途注入）

@dataclass
class AgentRunResult:
    final_content: str | None           # 最终回复内容
    messages: list[dict]                # 完整消息历史
    tools_used: list[str]               # 使用的工具列表
    usage: dict                         # token 用量
    stop_reason: str                    # 停止原因
    error: str | None                   # 错误信息
    had_injections: bool                # 是否有中途注入
```

### 3.2 核心循环 `run()`

```python
async def run(self, spec: AgentRunSpec) -> AgentRunResult:
    messages = list(spec.initial_messages)

    for iteration in range(spec.max_iterations):
        # ========== 第一阶段：上下文治理 ==========
        messages = self._drop_orphan_tool_results(messages)          # 清理孤儿工具结果
        messages = self._backfill_missing_tool_results(messages)     # 补全缺失的工具结果
        messages = self._microcompact(messages)                      # 微压缩旧工具结果
        messages = self._apply_tool_result_budget(spec, messages)    # 工具结果截断
        messages = self._snip_history(spec, messages)                # 上下文窗口裁剪

        # ========== 第二阶段：钩子 ==========
        await hook.before_iteration(context)

        # ========== 第三阶段：LLM 请求 ==========
        response = await self._request_model(spec, messages, hook, context)

        # ========== 第四阶段：分支处理 ==========
        if response.should_execute_tools:
            # 4a. 有工具调用 → 执行工具
            assistant_msg = build_assistant_message(response.tool_calls)
            self._emit_checkpoint("awaiting_tools", ...)
            tool_results = await self._execute_tools(response.tool_calls, spec)
            self._emit_checkpoint("tools_completed", ...)
            for tr in tool_results:
                messages.append(tr)
            # 处理中途注入
            # after_iteration 钩子
            # continue 下一轮

        elif response.has_tool_calls:
            # 4b. 工具调用但 finish_reason 不是 tool_use → 忽略工具
            pass

        # 4c. 空白回复重试（最多 2 次）
        # 4d. 长度恢复（截断但非空白，继续最多 3 轮）

        elif response.is_final:
            # 4e. 最终回复 → 退出循环
            messages.append(assistant_msg)
            break

    # 循环结束
    return AgentRunResult(...)
```

### 3.3 停止条件

| 停止原因 | 含义 |
|----------|------|
| `"completed"` | 正常的最终回复 |
| `"tool_error"` | 工具失败且 `fail_on_tool_error=True` |
| `"error"` | LLM 返回错误 |
| `"empty_final_response"` | 重试后仍为空白回复 |
| `"max_iterations"` | 耗尽最大迭代次数 |

### 3.4 上下文窗口管理

**`_snip_history()`** — 主要机制：

1. 预算 = `context_window_tokens - max_output_tokens - 1024（安全余量）`
2. 从后向前遍历消息，累加 token 直到预算耗尽
3. 始终保留 system 消息
4. 确保保留的消息以 `user` 开头（避免某些提供商拒绝 `system → assistant`）
5. 如果什么都放不下，回退到保留最后 4 条消息

**`_microcompact()`** — 微压缩：

将旧的工具结果（来自 `read_file`、`exec`、`grep` 等冗长工具）替换为一行摘要，仅保留最近 10 条完整结果。

### 3.5 错误恢复

| 机制 | 行为 |
|------|------|
| **空白回复重试** | 模型返回空白内容时，重试最多 2 次；之后尝试"最终化重试" |
| **长度恢复** | `finish_reason="length"` 但有内容时，追加续写提示，继续最多 3 轮 |
| **上下文治理失败** | 裁剪/压缩异常时，回退到最小修复（仅清理孤儿和补全） |

### 3.6 工具执行

```python
async def _execute_tools(self, tool_calls, spec):
    # 分区：连续的安全工具一起执行，不安全工具单独执行
    batches = self._partition_tool_batches(tool_calls)
    results = []
    for batch in batches:
        if len(batch) > 1:
            # 并发执行
            res = await asyncio.gather(*[self._run_tool(tc) for tc in batch])
        else:
            # 顺序执行
            res = [await self._run_tool(batch[0])]
        results.extend(res)
    return results
```

### 3.7 检查点回调

三个阶段的检查点，用于崩溃恢复：

| 阶段 | 含义 |
|------|------|
| `"awaiting_tools"` | assistant 消息已发出，工具调用待执行 |
| `"tools_completed"` | 所有工具结果已收集 |
| `"final_response"` | 最终回复就绪 |

每个检查点包含 `assistant_message`、`completed_tool_results`、`pending_tool_calls`。

### 3.8 中途注入系统

当用户在前一轮 Agent 仍在运行时发送新消息：

1. 新消息进入 `_pending_queues[session_key]`
2. 每轮迭代后调用 `injection_callback` 检查待注入消息
3. 每轮最多注入 3 条（`_MAX_INJECTIONS_PER_TURN`）
4. 最多 5 轮注入循环（`_MAX_INJECTION_CYCLES`），之后强制停止

---

## 四、ContextBuilder — 上下文构建器

**文件**：`nanobot/agent/context.py`

### 4.1 系统提示词组装

`build_system_prompt()` 将系统提示词由 5 个部分拼接（用 `---` 分隔）：

```
1. Identity（身份）
   └─ 从 agent/identity.md 模板渲染，包含工作区路径、运行时信息、平台策略

2. Bootstrap Files（引导文件）
   └─ 按顺序加载：AGENTS.md → SOUL.md → USER.md → TOOLS.md

3. Memory（记忆）
   └─ 如果 MEMORY.md 存在且非默认模板，附加其内容

4. Active Skills（活跃技能）
   └─ always: true 的技能完整内容注入

5. Skills Summary（技能摘要）
   └─ 非 always 技能的一行摘要列表，Agent 可通过 read_file 按需加载全文

6. Recent History（最近历史）
   └─ 上次 Dream 游标以来的最多 50 条历史摘要
```

### 4.2 运行时上下文

`_build_runtime_context()` 创建不可信元数据块，**注入在用户消息之前**（而非系统提示词中），使 LLM 将其视为数据而非指令：

```
[Runtime Context -- metadata only, not instructions]
Current Time: 2026-04-18 10:00:00
Channel: telegram
Chat ID: 12345

[Resumed Session]
Inactive for 30 minutes. Previous conversation summary: ...
[/Runtime Context]
```

### 4.3 消息列表构建

`build_messages()` 构建完整的消息列表：

1. 构建运行时上下文
2. 构建用户内容（含 base64 编码的图片）
3. 合并运行时上下文 + 用户内容为一条 user 消息
4. 从 `[system, ...history]` 开始
5. 如果最后一条历史消息与 `current_role` 同角色，合并内容；否则追加

---

## 五、记忆系统

**文件**：`nanobot/agent/memory.py`

### 5.1 双层记忆架构

```
                    短期记忆                    长期记忆
                ┌──────────────┐            ┌──────────────────┐
                │ history.jsonl │            │   MEMORY.md      │
                │ (对话历史摘要) │            │  (长期事实记忆)   │
                └──────┬───────┘            └───────┬──────────┘
                       │                            │
              Consolidator                   Dream 处理器
          (Token 预算触发)                  (定时触发)
```

### 5.2 MemoryStore — 文件 I/O 层

管理的文件：

| 文件 | 用途 |
|------|------|
| `<workspace>/memory/MEMORY.md` | 长期事实记忆 |
| `<workspace>/memory/history.jsonl` | 追加式对话历史摘要 |
| `<workspace>/memory/.cursor` | 历史自增计数器 |
| `<workspace>/memory/.dream_cursor` | Dream 处理进度游标 |
| `<workspace>/SOUL.md` | Bot 人格、行为、语气 |
| `<workspace>/USER.md` | 用户身份、偏好 |

关键方法：

```python
store.append_history(entry)          # 追加到 history.jsonl，返回 cursor
store.read_unprocessed_history(since_cursor)  # 读取未处理条目（供 Dream 使用）
store.compact_history()              # 截断到最近 max_history_entries 条
store.read_memory() / write_memory() # MEMORY.md 读写
store.read_soul() / write_soul()     # SOUL.md 读写
store.read_user() / write_user()     # USER.md 读写
```

### 5.3 Consolidator — Token 预算驱动整合

**触发条件**：当提示词超过 token 预算时（非定时器驱动）

```python
def maybe_consolidate_by_tokens(self, session):
    budget = context_window_tokens - max_completion_tokens - 1024
    target = budget // 2  # 目标：将提示词压缩到预算的一半

    for _ in range(5):  # 最多 5 轮
        tokens = self.estimate_session_prompt_tokens(session)
        if tokens <= target:
            break
        # 找到需要移除的消息边界（在 user 轮次处截断）
        end_idx, removed = self.pick_consolidation_boundary(session, tokens_to_remove)
        # 最多处理 60 条消息
        chunk = messages[:min(end_idx, 60)]
        # LLM 摘要 → 追加到 history.jsonl
        self.archive(chunk)
        session.last_consolidated += len(chunk)
```

**`archive()`** 使用 `agent/consolidator_archive.md` 模板指导 LLM：
> "提取关键事实：用户事实、决策、解决方案、事件、偏好"

### 5.4 Dream — 定时知识整合

两阶段流水线：

**Phase 1 — 分析**（纯 LLM 调用，无工具）：

1. 读取 `.dream_cursor` 以来未处理的 history.jsonl 条目
2. 读取当前 MEMORY.md、SOUL.md、USER.md
3. MEMORY.md 内容附加行龄标注（git blame，>14 天的行标注）
4. 发送给 LLM（`agent/dream_phase1.md` 模板），输出格式：
   - `[FILE] atomic fact` — 添加到 USER.md / SOUL.md / MEMORY.md
   - `[FILE-REMOVE] reason` — 删除冗余/过时内容
   - `[SKILL] kebab-case-name: description` — 标记可复用工作流

**Phase 2 — 执行**（AgentRunner + 文件工具）：

1. 列出已有技能（去重参考）
2. 使用 `AgentRunner`（最多 10 轮）执行文件编辑
3. 模板指导：**仅手术式编辑**（绝不重写整个文件）、在 `skills/<name>/SKILL.md` 创建技能
4. 工具事件记录日志，无论成功失败都推进 Dream 游标

**Git 自动提交**：Phase 2 后如有变更，自动 git commit，消息格式：
```
dream: 2024-01-15 10:30, 3 change(s)

{phase1_analysis}
```

### 5.5 GitStore — 版本化记忆

使用 dulwich（纯 Python git）对记忆文件做版本控制。

追踪文件：`SOUL.md`、`USER.md`、`memory/MEMORY.md`

```python
gitstore.init()               # 初始化 git 仓库
gitstore.auto_commit(message) # 自动提交变更
gitstore.line_ages(file_path) # git blame，返回每行的 age_days
gitstore.log(max_entries)     # 提交历史
gitstore.diff_commits(sha1, sha2)  # 差异比较
gitstore.revert(commit)       # 恢复到指定提交的父状态
```

**`.gitignore` 策略**：`/*` 排除一切，然后 `!SOUL.md`、`!USER.md`、`!memory/` 等选择性包含。这样 `git status` 只显示追踪文件的变更。

---

## 六、技能系统

**文件**：`nanobot/agent/skills.py`

### 6.1 技能发现

技能是带 YAML frontmatter 的 `SKILL.md` 文件：

```yaml
---
name: weather
description: "Get weather info from wttr.in"
metadata:
  nanobot:
    emoji: "🌤️"
    requires:
      bins: ["curl"]
      env: ["WEATHER_API_KEY"]
    always: true
---

## When to use
...
## Steps
...
```

**发现位置**：
- **内置技能**：`<nanobot_package>/skills/<name>/SKILL.md`
- **工作区技能**：`<workspace>/skills/<name>/SKILL.md`
- 工作区技能覆盖同名内置技能

### 6.2 渐进式加载设计

| 类型 | 加载方式 | 示例 |
|------|----------|------|
| **Always-on** | 系统提示词中注入完整内容 | `memory`、`my` |
| **Lazy-loaded** | 仅一行摘要出现在系统提示词中，Agent 通过 `read_file` 按需加载 | `github`、`weather`、`tmux` |

**设计动机**：保持基础提示词小巧，同时让所有技能可被发现。

### 6.3 依赖检查

```python
def _check_requirements(metadata):
    # bins: 检查命令是否在 PATH 中（shutil.which）
    for cmd in metadata.get("requires", {}).get("bins", []):
        if not shutil.which(cmd):
            return False
    # env: 检查环境变量是否设置
    for env_var in metadata.get("requires", {}).get("env", []):
        if not os.environ.get(env_var):
            return False
    return True
```

不满足条件的技能从上下文中排除。

---

## 七、工具系统

### 7.1 工具注册表

**文件**：`nanobot/agent/tools/registry.py`

```python
class ToolRegistry:
    def register(self, tool: Tool)          # 按 tool.name 注册
    def unregister(self, name: str)         # 按名称移除
    def get_definitions(self)               # 返回工具 Schema（内置在前，MCP 在后）
    def prepare_call(self, name, params)    # 执行前验证：类型检查 + 参数转换 + Schema 校验
    def execute(self, name, params)         # 执行工具，捕获所有异常
```

**`execute()` 安全策略**：
1. 先 `prepare_call()` 验证参数
2. 验证失败返回错误字符串 + 提示 `"[Analyze the error above and try a different approach.]"`
3. 执行结果以 "Error" 开头也追加同样提示
4. 所有异常都被捕获并格式化为错误字符串

### 7.2 工具基类

**文件**：`nanobot/agent/tools/base.py`

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...              # 工具名称

    @property
    @abstractmethod
    def description(self) -> str: ...       # 工具描述（给 LLM）

    @property
    @abstractmethod
    def parameters(self) -> dict: ...       # JSON Schema 参数定义

    @abstractmethod
    async def execute(self, **kwargs) -> str | list: ...  # 异步执行

    # 可配置属性
    read_only: bool = False                 # 无副作用，可并行
    exclusive: bool = False                 # 必须独占执行
    # 计算属性
    concurrency_safe = read_only and not exclusive
```

**Schema 验证**内置完整的 JSON Schema 验证器，支持：
- 类型检查（string / integer / number / boolean / array / object）
- 可空类型（`["string", "null"]`）
- 枚举、数值范围、字符串长度、对象必填项、数组长度和元素 Schema

### 7.3 工具参数装饰器

```python
@tool_parameters({
    "file_path": StringSchema(description="Path to the file"),
    "content": StringSchema(description="File content"),
})
class WriteFileTool(Tool):
    name = "write_file"
    # parameters 属性由装饰器自动提供
```

装饰器 `tool_parameters` 将 Schema 字典附加为 `parameters` 属性。

### 7.4 内置工具一览

| 工具 | 文件 | 功能 |
|------|------|------|
| `read_file` | `filesystem.py` | 读取文件内容 |
| `write_file` | `filesystem.py` | 写入文件 |
| `edit_file` | `filesystem.py` | 编辑文件（精确替换） |
| `list_dir` | `filesystem.py` | 列出目录内容 |
| `glob` | `search.py` | 文件名模式匹配 |
| `grep` | `search.py` | 内容搜索 |
| `notebook_edit` | `notebook.py` | Jupyter Notebook 编辑 |
| `exec` | `shell.py` | Shell 命令执行 |
| `web_search` | `web.py` | 网页搜索 |
| `web_fetch` | `web.py` | URL 内容抓取 |
| `message` | `message.py` | 向频道发消息 |
| `spawn` | `spawn.py` | 创建子 Agent |
| `cron` | `cron.py` | 定时任务 |
| `my` | `self.py` | 自我检查 |
| `mcp_*` | `mcp.py` | MCP 动态工具 |

---

## 八、子 Agent 系统

**文件**：`nanobot/agent/subagent.py`

### 8.1 子 Agent 与主 Agent 的区别

| 特性 | 主 Agent | 子 Agent |
|------|----------|----------|
| 工具集 | 完整工具集 | 受限：无 `message`、无 `spawn`、无 `cron` |
| 系统提示词 | 完整的身份+记忆+技能 | 简化的 `subagent_system.md` |
| 最大迭代 | 可配置 | 硬编码 15 |
| 错误处理 | 容错继续 | `fail_on_tool_error=True` |
| 结果传递 | OutboundMessage → Channel | InboundMessage(channel="system") → 主 Agent |

### 8.2 创建流程

```python
# 主 Agent 调用 spawn 工具
→ SpawnTool.execute(task="分析这个代码库", label="代码分析")
→ SubagentManager.spawn(task, label, origin_channel, origin_chat_id, session_key)
   → 生成 UUID 作为 task_id
   → 初始化 SubagentStatus
   → 创建 asyncio.Task 运行 _run_subagent()
   → 注册清理回调
```

### 8.3 结果回传

子 Agent 完成后，`_announce_result()` 创建 `InboundMessage`：

```python
InboundMessage(
    channel="system",
    sender_id="subagent",
    chat_id=f"{original_channel}:{original_chat_id}",
    content=rendered_template,  # subagent_announce.md
)
```

主 Agent 循环收到此消息后，将其视为 assistant 角色消息处理，继续对话。

### 8.4 状态追踪

```python
@dataclass
class SubagentStatus:
    task_id: str
    label: str
    task_description: str
    started_at: float
    phase: str  # initializing | awaiting_tools | tools_completed | final_response | done | error
    iteration: int
    tool_events: list
    usage: dict
    stop_reason: str | None
    error: str | None
```

可通过 `/stop` 命令按 session 取消所有子 Agent。

---

## 九、消息总线

**文件**：`nanobot/bus/queue.py` + `nanobot/bus/events.py`

### 9.1 设计

两个 `asyncio.Queue` 实现生产者-消费者解耦：

```
Channel ──publish_inbound──→ MessageBus.inbound ──consume_inbound──→ AgentLoop
AgentLoop ──publish_outbound──→ MessageBus.outbound ──consume_outbound──→ Channel
```

### 9.2 消息结构

**InboundMessage**（入站）：

```python
@dataclass
class InboundMessage:
    channel: str                    # "telegram" / "discord" / "cli" / "system"
    sender_id: str                  # 用户标识
    chat_id: str                    # 聊天/频道标识
    content: str                    # 消息文本
    timestamp: datetime             # 自动设为 now
    media: list[str]                # 媒体 URL（图片、文档）
    metadata: dict[str, Any]        # 频道特定数据
    session_key_override: str | None  # 可选的 session key 覆盖

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"
```

**OutboundMessage**（出站）：

```python
@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 支持流式标志: _stream_delta, _stream_end, _progress, _tool_hint 等
```

---

## 十、会话管理

**文件**：`nanobot/session/manager.py`

### 10.1 Session 数据结构

```python
@dataclass
class Session:
    key: str                     # "channel:chat_id"
    messages: list[dict]         # LLM 格式消息
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]     # 运行时检查点等
    last_consolidated: int       # 已整合到 history.jsonl 的消息索引
```

### 10.2 存储格式

JSONL 文件：`<workspace>/sessions/<safe_key>.jsonl`

```json
{"_type": "metadata", "key": "telegram:123", "created_at": "...", "metadata": {...}, "last_consolidated": 0}
{"role": "user", "content": "你好", "timestamp": "..."}
{"role": "assistant", "content": "你好！有什么可以帮你？", "timestamp": "..."}
```

第一行为元数据 JSON 对象，后续每行为一条消息。

### 10.3 会话生命周期

```
get_or_create(key)
  → 检查内存缓存
  → 命中则返回
  → 未命中则 _load(key) 从磁盘读取
     → 分离元数据行和消息行
     → 如果不存在则创建新 Session
  → 写入缓存并返回

save(session)
  → 覆盖写入 JSONL 文件（先元数据，后消息）

invalidate(key)
  → 从内存缓存中移除（下次访问时重新加载）
```

**边界规则**（`get_history` / `retain_recent_legal_suffix`）：
- 从 `last_consolidated` 索引开始取未整合的消息
- 对齐到合法的 tool-call 边界（以 user 轮次开始，丢弃开头孤儿工具结果）

---

## 十一、命令路由

**文件**：`nanobot/command/router.py` + `nanobot/command/builtin.py`

### 11.1 四级优先级系统

```python
class CommandRouter:
    _priority: dict[str, Handler]          # 精确匹配，调度锁前处理（/stop, /restart）
    _exact: dict[str, Handler]             # 精确匹配，调度锁内处理（/new, /dream）
    _prefix: list[tuple[str, Handler]]     # 最长前缀匹配（/dream-log <sha>）
    _interceptors: list[Handler]           # 兜底谓词
```

### 11.2 路由流程

```
AgentLoop.run():
  1. 消费 InboundMessage
  2. commands.is_priority(raw_text) → 是 → dispatch_priority（不创建 Task，/stop 即使在活跃调用中也能响应）
  3. 否 → 创建 asyncio.Task → _dispatch(msg)

_dispatch():
  4. commands.dispatch(ctx) → 返回 OutboundMessage → 发送并跳过正常 LLM 处理
  5. 无命令匹配 → 正常 _process_message()
```

### 11.3 内置命令

| 命令 | 优先级 | 处理器 | 功能 |
|------|--------|--------|------|
| `/stop` | priority | `cmd_stop` | 取消 session 的所有 Task 和子 Agent |
| `/restart` | priority | `cmd_restart` | 调用 `os.execv` 原地重启进程 |
| `/status` | priority + exact | `cmd_status` | 显示版本、模型、token 用量、会话大小、活动任务 |
| `/new` | exact | `cmd_new` | 清空 session，后台调度旧消息整合 |
| `/dream` | exact | `cmd_dream` | 触发 Dream.run() 作为后台任务 |
| `/dream-log` | exact + prefix | `cmd_dream_log` | 显示最新 Dream 提交差异，或指定 SHA |
| `/dream-restore` | exact + prefix | `cmd_dream_restore` | 列出最近提交或恢复指定 SHA |
| `/help` | exact | `cmd_help` | 显示可用命令列表 |

---

## 十二、生命周期钩子

**文件**：`nanobot/agent/hook.py`

### 12.1 钩子点（按执行顺序）

| 钩子 | 时机 | 异步 |
|------|------|------|
| `before_iteration(context)` | LLM 请求前 | 是 |
| `on_stream(context, delta)` | 每个流式增量 | 是 |
| `on_stream_end(context, resuming)` | 流式结束 | 是 |
| `before_execute_tools(context)` | 工具执行前 | 是 |
| `after_iteration(context)` | 迭代完成后 | 是 |
| `finalize_content(context, content)` | 最终内容处理 | 否（同步，管道式） |
| `wants_streaming()` | 查询是否启用流式 | 否 |

### 12.2 钩子上下文

```python
@dataclass
class AgentHookContext:
    iteration: int                      # 当前迭代次数
    messages: list[dict]                # 完整消息列表
    response: LLMResponse | None        # LLM 响应
    usage: dict[str, int]               # token 用量
    tool_calls: list[ToolCallRequest]   # 工具调用列表
    tool_results: list[Any]             # 工具结果
    tool_events: list[dict]             # 工具事件日志
    final_content: str | None           # 最终回复内容
    stop_reason: str | None             # 停止原因
    error: str | None                   # 错误信息
```

### 12.3 CompositeHook — 组合模式

```python
class CompositeHook(AgentHook):
    def __init__(self, hooks: list[AgentHook], reraise: bool = False):
        self.hooks = hooks

    # 异步方法使用 _for_each_hook_safe()：逐个调用，捕获每个钩子的异常
    # 确保有缺陷的自定义钩子不会导致 AgentLoop 崩溃

    # finalize_content 是管道式（无异常隔离）：
    # 每个钩子的输出作为下一个钩子的输入
    # 内容转换的 bug 应该暴露出来
```

---

## 十三、自动压缩

**文件**：`nanobot/agent/autocompact.py`

### 13.1 工作机制

```
AgentLoop.run() 每 1 秒超时:
  → auto_compact.check_expired()
     → 遍历所有 session
        → 跳过正在归档的 key
        → 跳过有待注入队列的 key（活跃任务中）
        → 如果 updated_at 超过 TTL，后台启动 _archive()
```

### 13.2 归档流程 `_archive()`

1. 从内存缓存中使 session 失效
2. 从磁盘重新加载
3. 分割消息：
   - **archive_msgs**：旧的、待摘要的消息
   - **kept_msgs**：最近 8 条保留消息（`_RECENT_SUFFIX_MESSAGES`）
4. 调用 `consolidator.archive(archive_msgs)` 获取 LLM 摘要
5. 将摘要存入 `_summaries` 字典和 `session.metadata["_last_summary"]`
6. 用保留的后缀替换 session 消息
7. 保存 session

### 13.3 准备会话 `prepare_session()`

在每次 `_process_message()` 开始时调用：
- 如果 session 正在归档或已过期，从磁盘重载
- 检查摘要（先在 `_summaries` 缓存，再在 `session.metadata` 中）
- 格式化为：`"Inactive for N minutes.\nPrevious conversation summary: {text}"`

### 13.4 重写行为

自动压缩会**原地重写 session JSONL 文件**：
- 旧消息（包括结构化的 `tool_calls` / `tool_call_id` / `reasoning_content`）被替换为仅保留的后缀
- 归档的前缀仅以纯文本摘要形式保留在 `memory/history.jsonl` 中
- 原始结构化 JSON 不再可从 session 文件恢复

> 这不同于 token 驱动的软整合（仅推进 `last_consolidated` 游标，不触碰 session 文件）。
> 如果需要完整的工具调用审计链，建议将 `idleCompactAfterMinutes` 保持为默认 `0`。

---

## 十四、二次开发指南

### 14.1 扩展新工具

```python
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schemas import StringSchema, IntegerSchema

@tool_parameters({
    "query": StringSchema(description="Search query", min_length=1),
    "limit": IntegerSchema(description="Max results", minimum=1, maximum=20, default=5),
})
class MySearchTool(Tool):
    name = "my_search"
    description = "Search my custom database"
    read_only = True  # 无副作用，可并行执行

    async def execute(self, query: str, limit: int = 5) -> str:
        # 实现搜索逻辑
        results = await self._search(query, limit)
        return format_results(results)

# 注册到 AgentLoop
loop.tools.register(MySearchTool())
```

### 14.2 扩展新频道

```python
from nanobot.channels.base import BaseChannel

class MyChannel(BaseChannel):
    name = "my_platform"

    async def start(self):
        # 连接平台，开始接收消息
        ...

    async def stop(self):
        # 断开连接
        ...

    async def send(self, msg: OutboundMessage):
        # 发送消息到平台
        ...

    async def send_delta(self, delta: str, metadata: dict):
        # 流式增量发送（可选）
        ...

    # 消息到达时调用：
    # self._handle_message(InboundMessage(...))
```

### 14.3 扩展新技能

在工作区创建技能目录：

```
<workspace>/skills/my-skill/
└── SKILL.md
```

```yaml
---
name: my-skill
description: "执行某项特定任务"
metadata:
  nanobot:
    emoji: "🔧"
    requires:
      bins: ["my-cli-tool"]
      env: ["MY_API_KEY"]
---

## When to use
当用户需要...时使用此技能。

## Steps
1. 首先...
2. 然后...
3. 最后...
```

### 14.4 添加生命周期钩子

```python
from nanobot.agent.hook import AgentHook, AgentHookContext

class LoggingHook(AgentHook):
    async def before_iteration(self, ctx: AgentHookContext) -> None:
        print(f"Iteration {ctx.iteration}")

    async def after_iteration(self, ctx: AgentHookContext) -> None:
        print(f"Tools: {ctx.tool_calls}, Usage: {ctx.usage}")

    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            print(f"Calling: {tc.name}({tc.arguments})")

# 使用
loop = AgentLoop(..., hooks=[LoggingHook()])
```

### 14.5 作为 Python 库使用

```python
from nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Summarize the README")
print(result.content)

# 带会话隔离
await bot.run("hi", session_key="user-alice")
await bot.run("hi", session_key="task-42")

# 带钩子
from nanobot.agent import AgentHook, AgentHookContext

class AuditHook(AgentHook):
    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            print(f"[tool] {tc.name}")

result = await bot.run("Hello", hooks=[AuditHook()])
```

### 14.6 扩展新 LLM 提供商

只需两步：

**Step 1**：在 `nanobot/providers/registry.py` 添加 `ProviderSpec`：

```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    env_key="MYPROVIDER_API_KEY",
    display_name="My Provider",
    default_api_base="https://api.myprovider.com/v1",
)
```

**Step 2**：在 `nanobot/config/schema.py` 的 `ProvidersConfig` 中添加字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

自动生效：环境变量解析、模型路由、配置匹配、`nanobot status` 显示。

### 14.7 常见扩展点

| 想做什么 | 修改哪里 |
|----------|----------|
| 添加新工具 | `nanobot/agent/tools/` 创建文件，继承 `Tool` |
| 添加新频道 | `nanobot/channels/` 创建文件，继承 `BaseChannel` |
| 添加新技能 | `<workspace>/skills/<name>/SKILL.md` |
| 修改系统提示词 | 编辑 `nanobot/templates/` 下的模板 |
| 自定义身份 | 编辑 `<workspace>/SOUL.md` |
| 自定义 Agent 指令 | 编辑 `<workspace>/AGENTS.md` |
| 自定义用户画像 | 编辑 `<workspace>/USER.md` |
| 添加工具使用备注 | 编辑 `<workspace>/TOOLS.md` |
| 添加新 LLM 提供商 | `providers/registry.py` + `config/schema.py` |
| 自定义生命周期行为 | 添加 `AgentHook` 子类 |
| 修改记忆行为 | `nanobot/agent/memory.py` |

### 14.8 开发调试建议

```python
# 开启详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 使用 nanobot agent --logs 查看运行时日志
# nanobot agent --logs
```

关键日志观察点：
- 工具调用和结果
- Token 用量
- 会话加载/保存
- Dream 处理过程
- 命令路由匹配

---

## 附录：关键设计模式总结

| 模式 | 应用场景 | 好处 |
|------|----------|------|
| **两层循环架构** | AgentLoop（产品关注）→ AgentRunner（纯 LLM 循环） | 子 Agent/Dream 可复用 Runner |
| **组合钩子模式** | CompositeHook 扇出生命周期事件 | 自定义钩子故障不影响核心循环 |
| **检查点崩溃恢复** | 每阶段持久化 in-flight 状态 | 进程崩溃后可恢复未完成轮次 |
| **中途消息注入** | 活跃任务中排入待注入队列 | 实时对话，无需等待当前轮次完成 |
| **渐进式技能加载** | 摘要 + 按需 read_file | 基础提示词小，所有技能可发现 |
| **文件化持久化** | JSONL + Markdown 文件 | 人类可读、易调试、无需数据库 |
| **双层记忆** | Consolidator（响应式）+ Dream（主动式） | 既要控制 token 又要持续学习 |
| **版本化记忆** | GitStore 自动提交 | 记忆审计和回滚（`/dream-restore`） |
| **消息总线解耦** | Channel ↔ Agent 仅通过消息类型通信 | 新增频道零侵入 |
| **子 Agent 一等公民** | 独立 LLM 调用 + 独立工具集 + 总线回传 | 后台任务不阻塞主对话 |
