# Nanobot 项目分析报告

> 生成日期：2026-04-18
> 项目版本：v0.1.5.post1
> 许可证：MIT

---

## 一、项目概述

**Nanobot** 是一个轻量级的个人 AI Agent 框架，灵感来源于 OpenClaw。其核心理念是以极少的代码量（比同类框架少 99% 的代码行数）实现完整的 AI Agent 功能。项目面向需要稳定长期运行的 AI Agent 部署场景，支持对接多种聊天平台或以 CLI 方式运行。

**核心卖点：**

- 一条命令完成配置（`nanobot onboard`），仅需 API Key + 模型名称即可启动
- 内置支持 12+ 聊天平台（Telegram、Discord、WhatsApp、微信、飞书、钉钉、Slack、Matrix、Email、QQ、企业微信、MS Teams 等）
- 完整的工具系统（Shell 执行、文件操作、网页搜索、MCP 集成、Cron 定时任务）
- 双层记忆系统 + "Dream" 自动知识整合
- 后台子 Agent 系统，支持长时间运行的后台任务
- OpenAI 兼容的 API Server（`nanobot serve`）
- Python SDK（`from nanobot import Nanobot`）

---

## 二、技术栈

| 类别 | 技术选型 |
|------|----------|
| 语言 | Python 3.11+ |
| LLM SDK | `anthropic`（Claude 原生）、`openai`（OpenAI 兼容） |
| MCP 协议 | `mcp` |
| 数据验证 | Pydantic v2 + pydantic-settings |
| CLI 框架 | Typer + prompt_toolkit + questionary + Rich |
| 日志 | loguru |
| 异步 | asyncio（全链路异步） |
| WebSocket | websockets（服务端）、websocket-client（客户端） |
| HTTP 客户端 | httpx |
| 搜索引擎 | ddgs（DuckDuckGo） |
| 聊天平台 SDK | dingtalk-stream、python-telegram-bot、lark-oapi、qq-botpy、python-socketio、slack-sdk、wecom-aibot-sdk-python 等 |
| 模板引擎 | Jinja2 |
| 文档解析 | pypdf、python-docx、openpyxl、python-pptx |
| Git 操作 | dulwich |
| WhatsApp Bridge | TypeScript + Baileys |
| 构建工具 | hatchling |
| 代码检查 | ruff |
| 测试框架 | pytest + pytest-asyncio + pytest-cov |

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Chat Platforms                           │
│  Telegram │ Discord │ WhatsApp │ 微信 │ 飞书 │ 钉钉 │ Slack │... │
└───────┬─────────────┬────────────┬───────┬───────┬──────┬───────┘
        │             │            │       │       │      │
        ▼             ▼            ▼       ▼       ▼      ▼
┌─────────────────────────────────────────────────────────────┐
│                      Channel Layer                           │
│  BaseChannel 抽象 → 各平台具体实现 → InboundMessage 封装      │
└────────────────────────────┬────────────────────────────────┘
                             │ publish
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       MessageBus                             │
│         inbound Queue  ←→  outbound Queue                    │
└────────────────────────────┬────────────────────────────────┘
                             │ consume
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       AgentLoop                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ ContextBuilder│ │ SessionManager│ │ AutoCompact        │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ AgentRunner  │ │ ToolRegistry  │ │ SubagentManager    │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│  ┌─────────────┐  ┌──────────────┐                           │
│  │ MemoryStore  │ │ Dream Service│                            │
│  └─────────────┘  └──────────────┘                           │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     LLM Provider                             │
│  Anthropic │ OpenAI │ OpenRouter │ Ollama │ Groq │ Gemini... │
└─────────────────────────────────────────────────────────────┘
```

**数据流：**

1. `BaseChannel` 子类从平台接收消息
2. 封装为 `InboundMessage` 发布到 `MessageBus.inbound` 队列
3. `AgentLoop` 消费消息，构建上下文，调用 LLM
4. LLM 返回的工具调用通过 `ToolRegistry` 执行
5. 最终响应封装为 `OutboundMessage` 发布到 `MessageBus.outbound` 队列
6. `ChannelManager` 从 outbound 队列拉取消息并路由到对应频道

### 3.2 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Python SDK 入口 | `nanobot/__init__.py`、`nanobot/nanobot.py` | 版本管理，`Nanobot.from_config()` 编程式接口 |
| Agent 核心 | `nanobot/agent/loop.py` (~45K) | 消息路由、会话管理、工具执行、流式钩子、自动压缩、Dream 集成 |
| Agent 执行器 | `nanobot/agent/runner.py` (~34K) | 通用 LLM 工具调用循环，上下文管理、错误恢复、Token 估算 |
| 上下文构建 | `nanobot/agent/context.py` | 系统提示词组装：身份模板 + 引导文件 + 记忆 + 技能 |
| 消息总线 | `nanobot/bus/queue.py` | 两个 `asyncio.Queue`（inbound/outbound）实现解耦 |
| 事件模型 | `nanobot/bus/events.py` | `InboundMessage` / `OutboundMessage` 数据类 |
| 频道管理 | `nanobot/channels/manager.py` | 频道生命周期管理、outbound 分发、重试/合并 |
| 频道注册 | `nanobot/channels/registry.py` | 自动发现内置频道 + entry_points 外部插件 |
| 频道基类 | `nanobot/channels/base.py` | 抽象接口：`start()`, `stop()`, `send()`, `send_delta()` |
| 提供商注册 | `nanobot/providers/registry.py` | ProviderSpec 元数据，关键词自动检测 |
| 配置系统 | `nanobot/config/schema.py` | Pydantic 完整配置 Schema |
| CLI | `nanobot/cli/commands.py` (~56K) | Typer CLI：agent/gateway/serve/onboard/status 等 |
| 配置引导 | `nanobot/cli/onboard.py` | 交互式设置向导 |
| 命令路由 | `nanobot/command/router.py` | 聊天内命令：/new、/stop、/restart、/status、/dream 等 |
| Cron 服务 | `nanobot/cron/service.py` (~21K) | 定时任务管理（cron 表达式） |
| 心跳服务 | `nanobot/heartbeat/service.py` | 周期性唤醒，检查 HEARTBEAT.md 任务 |
| 会话管理 | `nanobot/session/manager.py` | 持久化会话存储（每 session 一个 JSONL 文件） |
| 工具注册 | `nanobot/agent/tools/registry.py` | `ToolRegistry` 注册和执行工具 |
| 记忆系统 | `nanobot/agent/memory.py` (~34K) | MemoryStore、Consolidator、Dream、GitStore |
| 技能系统 | `nanobot/agent/skills.py` | SkillsLoader：加载/校验/渲染技能摘要 |
| 子 Agent | `nanobot/agent/subagent.py` | 后台任务执行，独立工具集，状态追踪 |
| 自动压缩 | `nanobot/agent/autocompact.py` | 空闲超时后主动压缩会话上下文 |
| 生命周期钩子 | `nanobot/agent/hook.py` | before_iteration、on_stream、before_execute_tools 等 |
| 提示词模板 | `nanobot/utils/prompt_templates.py` | Jinja2 模板渲染 |
| API Server | `nanobot/api/server.py` | OpenAI 兼容的 HTTP API |

---

## 四、频道集成（Channel）

内置支持的聊天平台共 14 个：

| 频道 | 文件 | 传输方式 | 备注 |
|------|------|----------|------|
| **Telegram** | `telegram.py` (~45K) | Polling/Long-poll | 推荐首选，完整多模态支持 |
| **Discord** | `discord.py` (~27K) | Bot Gateway | 需要 Message Content Intent |
| **WhatsApp** | `whatsapp.py` (~13K) | WebSocket（通过 Bridge） | 需要 Node.js Bridge (`bridge/`) |
| **微信 (Weixin)** | `weixin.py` (~57K) | HTTP Long-poll | 通过 ilinkai 个人 API，扫码登录 |
| **飞书 (Feishu)** | `feishu.py` (~68K) | WebSocket | 支持 CardKit 流式，中国/Lark 域 |
| **钉钉 (DingTalk)** | `dingtalk.py` (~26K) | Stream 模式 | 无需公网 IP |
| **Slack** | `slack.py` (~18K) | Socket Mode | 无需公网 URL |
| **Matrix** | `matrix.py` (~38K) | matrix-nio | 支持端到端加密，不支持 Windows |
| **Email** | `email.py` (~25K) | IMAP/SMTP | 轮询 IMAP，SMTP 回复 |
| **QQ** | `qq.py` (~25K) | botpy SDK WebSocket | 仅支持私聊 |
| **企业微信 (WeCom)** | `wecom.py` (~22K) | WebSocket | 企业微信 |
| **MS Teams** | `msteams.py` (~22K) | HTTP Webhook | MVP，仅 DM，需公网端点 |
| **Mochat** | `mochat.py` (~39K) | Socket.IO WebSocket | Claw IM + HTTP 降级 |
| **WebSocket** | `websocket.py` (~18K) | WebSocket Server | 自定义客户端，支持流式 |

频道支持插件扩展机制，通过 Python `entry_points`（`nanobot.channels` 组）注册外部插件频道。

---

## 五、工具系统（Tool）

工具通过 `ToolRegistry` 注册，每个工具包含 schema（名称、描述、参数）和异步 `execute` 方法。

### 5.1 内置工具

| 工具 | 文件 | 功能 |
|------|------|------|
| `exec` | `shell.py` (~13K) | Shell 命令执行，超时控制、危险命令拦截、bwrap 沙箱 |
| `read_file` / `write_file` / `edit_file` / `list_dir` | `filesystem.py` (~34K) | 文件操作，支持工作区限制 |
| `web_search` / `web_fetch` | `web.py` (~19K) | 网页搜索（DuckDuckGo/Brave/Tavily/Jina/Kagi/SearXNG）和 URL 抓取 |
| `grep` / `glob` | `search.py` (~21K) | 代码/内容搜索和文件发现 |
| `message` | `message.py` | 向指定聊天频道发送消息 |
| `cron` | `cron.py` | 创建/列出/删除定时提醒 |
| `spawn` | `spawn.py` | 启动后台子 Agent 任务 |
| `my` | `self.py` (~21K) | 自我检查 — Agent 查询自身运行时状态 |
| `mcp_*` | `mcp.py` (~20K) | 动态 MCP 服务器工具注册（stdio 和 HTTP 传输） |
| `notebook_edit` | `notebook.py` | Jupyter Notebook 单元格编辑 |
| `sandbox` | `sandbox.py` | Bubblewrap 沙箱后端 |

### 5.2 MCP 集成

支持在配置中声明外部 MCP 服务器（`tools.mcpServers`），传输方式包括：
- **stdio**：`command` + `args`
- **HTTP**：`url` + `headers`

工具自动发现并注册，支持 `enabledTools` 过滤和 per-server 超时设置。

---

## 六、Agent 系统设计

### 6.1 AgentLoop 工作流程

1. **消息消费**：从 `MessageBus.inbound` 拉取消息，按 session 创建 asyncio Task
2. **会话管理**：`SessionManager` 以 `channel:chat_id` 为 key 加载/保存 JSONL 历史
3. **上下文构建**：`ContextBuilder` 组装系统提示词
4. **LLM 调用**：`AgentRunner` 处理工具调用循环
5. **工具执行**：通过 `ToolRegistry` 执行，结果追加到消息列表
6. **子 Agent**：`SubagentManager` 运行独立工具集的后台任务
7. **自动压缩**：`AutoCompact` 在可配置超时后压缩空闲会话
8. **Dream**：定时记忆整合，编辑 SOUL.md / USER.md / MEMORY.md

### 6.2 生命周期钩子（Hook）

`AgentHook` 支持观察/自定义以下生命周期事件：
- `before_iteration` — 每次迭代前
- `on_stream` / `on_stream_end` — 流式输出中/结束
- `before_execute_tools` — 工具执行前
- `after_iteration` — 迭代结束后
- `finalize_content` — 内容最终化

---

## 七、记忆系统

### 7.1 双层记忆

1. **短期记忆**：`history.jsonl` — 每次对话的消息记录
2. **长期记忆**：`MEMORY.md` — 语义化记忆文件（用户偏好、反馈、项目信息、外部引用）

### 7.2 核心组件

| 组件 | 职责 |
|------|------|
| `MemoryStore` | 管理 history.jsonl 和 MEMORY.md 的读写 |
| `Consolidator` | Token 驱动的摘要压缩，将旧消息压缩为摘要 |
| `Dream` | 定时知识整合服务，自动编辑 SOUL.md / USER.md / MEMORY.md |
| `GitStore` | 版本化记忆，使用 dulwich 对记忆变更做 Git 记录 |

记忆文件存储在 `~/.nanobot/projects/<workspace>/memory/` 目录下，按类型（user / feedback / project / reference）分类。

---

## 八、技能系统（Skills）

技能以 `SKILL.md` Markdown 文件形式组织，包含 YAML frontmatter 元数据：

```yaml
---
name: skill-name
description: "技能描述"
metadata: {"nanobot":{"emoji":"X","requires":{"bins":["cmd"]}}}
---
```

### 8.1 技能加载

- **内置技能**：位于 `nanobot/skills/`，共 9 个
- **工作区技能**：位于 `<workspace>/skills/`，可覆盖同名内置技能
- 技能可声明依赖（`bins`、`env`），不满足条件的技能从上下文中排除
- `always: true` 的技能始终注入系统提示词
- 其他技能以摘要形式呈现，Agent 可通过 `read_file` 探索详情

### 8.2 内置技能列表

| 技能 | 用途 |
|------|------|
| `clawhub` | 从 ClawHub 公共仓库搜索/安装技能 |
| `cron` | Cron 定时任务使用指南 |
| `github` | GitHub CLI (`gh`) 操作指南 |
| `memory` | 双层记忆系统使用指南（always-on） |
| `my` | 自我检查工具使用指南（always-on） |
| `skill-creator` | 创建新技能的指南 |
| `summarize` | 文本摘要 |
| `tmux` | 终端复用器管理 |
| `weather` | 天气查询（wttr.in，无需 API Key） |

---

## 九、模板系统

模板位于 `nanobot/templates/`，使用 Jinja2 引擎渲染。

### 9.1 关键模板

| 模板 | 用途 |
|------|------|
| `agent/identity.md` | Agent 核心身份（工作区路径、平台格式提示、执行规则） |
| `agent/platform_policy.md` | 平台特定的格式指南 |
| `agent/skills_section.md` | 技能摘要部分的格式 |
| `SOUL.md` | 默认 Bot 人格 |
| `USER.md` | 默认用户画像模板 |
| `AGENTS.md` | 默认 Agent 指令 |
| `TOOLS.md` | 工具使用说明 |
| `memory/MEMORY.md` | 默认长期记忆模板 |

模板在 `nanobot onboard` 时通过 `sync_workspace_templates()` 同步到工作区。系统会检测文件是否仍为默认模板（以跳过将其作为自定义记忆加载）。

---

## 十、配置系统

根配置使用 Pydantic v2 + pydantic-settings，支持：
- camelCase 和 snake_case 键名
- `${VAR_NAME}` 环境变量引用
- `NANOBOT__` 环境变量前缀嵌套配置

### 10.1 配置结构

```
Config
├── agents.defaults
│   ├── workspace, model, provider, max_tokens, context_window_tokens
│   ├── temperature, max_tool_iterations, max_tool_result_chars
│   ├── reasoning_effort, timezone, unified_session
│   ├── disabled_skills, session_ttl_minutes（自动压缩超时）
│   └── dream（interval_h, max_batch_size, max_iterations, annotate_line_ages）
├── channels
│   ├── send_progress, send_tool_hints, send_max_retries, transcription_provider
│   └── 各频道独立配置（extra="allow"）
├── providers
│   ├── custom, anthropic, openai, openrouter, deepseek, groq
│   ├── azure_openai, zhipu, dashscope, vllm, ollama, lm_studio, ovms
│   ├── gemini, moonshot, minimax, minimax_anthropic, mistral
│   ├── stepfun, xiaomi_mimo, aihubmix, siliconflow
│   ├── volcengine, volcengine_coding_plan
│   ├── byteplus, byteplus_coding_plan
│   └── openai_codex, github_copilot, qianfan
├── api（host, port, timeout）
├── gateway（host, port, heartbeat 配置）
└── tools
    ├── web（enable, proxy, search provider）
    ├── exec（enable, timeout, sandbox, path_append）
    ├── my（enable, allow_set）
    ├── restrict_to_workspace
    ├── mcp_servers
    └── ssrf_whitelist
```

### 10.2 提供商匹配

通过 `ProviderSpec` 注册表实现关键词自动检测，支持显式指定提供商，回退到第一个可用的 keyed provider。

---

## 十一、部署方式

| 方式 | 命令 | 说明 |
|------|------|------|
| **CLI 交互** | `nanobot agent` | 交互式聊天 |
| **CLI 单次** | `nanobot agent -m "..."` | 单次运行 |
| **Gateway** | `nanobot gateway` | 启动所有频道 + Agent 循环（长期运行） |
| **API Server** | `nanobot serve` | OpenAI 兼容 API，默认 `127.0.0.1:8900` |
| **Docker** | `docker compose up` | 含 WhatsApp Bridge，非 root 用户（UID 1000） |
| **systemd** | 用户服务 | README 中提供示例 |
| **多实例** | `--config` / `--workspace` | 运行独立 Bot |
| **Python SDK** | `from nanobot import Nanobot` | 编程式使用 |

### 11.1 Docker Compose 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `gateway` | 18790 | Gateway 模式 |
| `api` | 8900 | API Server |
| `cli` | - | CLI 模式（profile: cli） |

数据持久化：`~/.nanobot:/home/nanobot/.nanobot` 卷挂载。

---

## 十二、测试体系

测试框架：pytest + pytest-asyncio（auto mode）+ coverage 报告。

### 12.1 测试覆盖范围

| 测试 | 目的 |
|------|------|
| `test_api_attachment.py` | API 文件上传（base64、multipart） |
| `test_api_stream.py` | API 流式（SSE） |
| `test_build_status.py` | 构建和状态检查 |
| `test_context_documents.py` | 上下文文档处理 |
| `test_docker.sh` | Docker 构建/运行验证 |
| `test_document_parsing.py` | PDF、Word、Excel、PPTX 文档解析 |
| `test_msteams.py` | MS Teams 频道 |
| `test_nanobot_facade.py` | Python SDK 入口 |
| `test_openai_api.py` | OpenAI 兼容 API |
| `test_package_version.py` | 版本解析 |
| `test_truncate_text_shadowing.py` | 文本截断 |
| `tests/tools/` | 各工具专项测试 |
| `tests/utils/` | 工具函数测试 |
| `tests/agent/`, `tests/channels/`, `tests/cli/` 等 | 按模块测试 |

### 12.2 CI 矩阵

- **触发**：push 到 `main`/`nightly`，pull_request 到 `main`/`nightly`
- **平台**：Ubuntu + Windows
- **Python 版本**：3.11 / 3.12 / 3.13 / 3.14
- **步骤**：Checkout → Python 安装 → uv 安装 → 系统依赖 → `uv sync --all-extras` → `ruff check` → `pytest`

---

## 十三、项目目录结构

```
nanobot/
├── nanobot/                    # 核心 Python 包
│   ├── __init__.py             # 包入口，版本管理
│   ├── nanobot.py              # Nanobot SDK 门面
│   ├── agent/                  # Agent 核心
│   │   ├── loop.py             # 主循环（最大文件 ~45K）
│   │   ├── runner.py           # 通用 LLM 工具调用循环
│   │   ├── context.py          # 上下文构建器
│   │   ├── memory.py           # 记忆系统
│   │   ├── skills.py           # 技能加载
│   │   ├── subagent.py         # 子 Agent
│   │   ├── hook.py             # 生命周期钩子
│   │   ├── autocompact.py      # 自动压缩
│   │   └── tools/              # 工具实现
│   │       ├── base.py         # 工具基类
│   │       ├── registry.py     # 工具注册表
│   │       ├── shell.py        # Shell 执行
│   │       ├── filesystem.py   # 文件操作
│   │       ├── web.py          # 网页搜索/抓取
│   │       ├── search.py       # 代码搜索
│   │       ├── mcp.py          # MCP 集成
│   │       ├── cron.py         # 定时任务
│   │       ├── spawn.py        # 后台任务
│   │       ├── self.py         # 自我检查
│   │       ├── message.py      # 消息发送
│   │       ├── sandbox.py      # 沙箱
│   │       └── notebook.py     # Notebook 编辑
│   ├── channels/               # 频道实现
│   │   ├── base.py             # 抽象基类
│   │   ├── manager.py          # 频道管理器
│   │   ├── registry.py         # 频道注册
│   │   ├── telegram.py         # Telegram
│   │   ├── discord.py          # Discord
│   │   ├── whatsapp.py         # WhatsApp
│   │   ├── weixin.py           # 微信
│   │   ├── feishu.py           # 飞书
│   │   ├── dingtalk.py         # 钉钉
│   │   ├── slack.py            # Slack
│   │   ├── matrix.py           # Matrix
│   │   ├── email.py            # Email
│   │   ├── qq.py               # QQ
│   │   ├── wecom.py            # 企业微信
│   │   ├── msteams.py          # MS Teams
│   │   ├── mochat.py           # Mochat
│   │   └── websocket.py        # WebSocket
│   ├── bus/                    # 消息总线
│   ├── cli/                    # CLI 命令
│   ├── command/                # 命令路由
│   ├── config/                 # 配置 Schema
│   ├── providers/              # LLM 提供商
│   ├── cron/                   # Cron 服务
│   ├── heartbeat/              # 心跳服务
│   ├── session/                # 会话管理
│   ├── api/                    # API Server
│   ├── skills/                 # 内置技能 SKILL.md
│   ├── templates/              # Jinja2 模板
│   └── utils/                  # 工具函数
├── bridge/                     # WhatsApp Bridge (TypeScript)
├── tests/                      # 测试
├── docs/                       # 文档
├── .github/workflows/          # CI 配置
├── pyproject.toml              # 项目配置
├── Dockerfile                  # Docker 构建
├── docker-compose.yml          # Docker Compose
├── README.md                   # 项目说明
├── CONTRIBUTING.md             # 贡献指南
├── SECURITY.md                 # 安全策略
└── entrypoint.sh               # Docker 入口脚本
```

---

## 十四、项目优势与特点

1. **极简设计**：以极少代码实现完整功能，降低维护成本和认知负担
2. **插件化架构**：频道、工具、技能、提供商均支持插件扩展
3. **多平台覆盖**：国内外主流聊天平台均有适配（Telegram、Discord、微信、飞书、钉钉、QQ、企业微信等）
4. **多提供商支持**：30+ LLM 提供商（Anthropic、OpenAI、Gemini、Ollama、智谱、通义千问、MiniMax 等）
5. **记忆与学习**：双层记忆 + Dream 自动整合，Agent 能随时间"成长"
6. **安全可靠**：Shell 沙箱（Bubblewrap）、SSRF 白名单、工作区限制、危险命令拦截
7. **部署灵活**：CLI / Gateway / API / Docker / systemd / Python SDK 多种方式
8. **OpenAI 兼容 API**：可被任意 OpenAI SDK 客户端直接调用

---

## 十五、总结

Nanobot 是一个设计精良的轻量级 AI Agent 框架。其核心优势在于以极简的代码实现了完整的 Agent 能力，同时对国内外聊天平台和 LLM 提供商的广泛覆盖使其具有很强的实用性。MessageBus 的解耦设计、插件化的扩展机制、双层记忆系统以及 Dream 自动整合等特性，都体现了良好的架构设计思维。
