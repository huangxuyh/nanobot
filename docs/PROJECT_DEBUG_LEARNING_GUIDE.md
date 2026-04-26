# 项目学习与调试指南

本文档面向你现在这套已经构建好的 `nanobot` + CAE skill + WebUI/gateway 系统，目标是帮助你：

1. 先快速建立整个项目的全局认知
2. 知道主链路是怎么跑起来的
3. 知道出现问题时该从哪里开始下断点
4. 知道不同类型的问题该看哪些变量和文件

本文档会尽量结合你当前已经跑通的内容来讲：

- WebUI
- `nanobot gateway`
- WebSocket channel
- `AgentLoop`
- skill / subagent
- blocking HITL
- workflow store
- CAE 领域请求过滤

---

## 1. 建议的学习顺序

不要一上来就通读整个仓库。这个项目已经不小了，最有效的方式是按“主执行链”学习。

推荐顺序：

1. 先理解入口
2. 再理解消息是如何进入 AgentLoop 的
3. 再理解 AgentLoop 如何：
   - 构建上下文
   - 调 LLM
   - 跑工具
   - 触发 skill / subagent
4. 再理解 workflow / HITL / subagent 状态机
5. 最后再理解 WebUI 与 guardrail

如果你按这个顺序走，理解成本最低。

---

## 2. 先建立全局图

你现在最常用的实际运行链路是：

```text
WebUI
  -> WebSocket channel
  -> MessageBus
  -> AgentLoop
  -> ContextBuilder
  -> AgentRunner
  -> ToolRegistry / tools
  -> skill / spawn / subagent
  -> WorkflowStore / SessionManager
  -> OutboundMessage
  -> WebSocket
  -> WebUI
```

如果是命中 CAE 主 skill，那么中间会进一步变成：

```text
用户请求
  -> AgentLoop._process_message()
  -> CAE guardrail
  -> skill 命中
  -> SpawnTool
  -> SubagentManager.spawn_task()
  -> 子 skill 返回 needs_user_input / ok
  -> WorkflowStore 更新状态
  -> 用户继续回复
  -> _resume_blocked_workflow()
  -> 下一轮 subagent
  -> 产物脚本生成
```

---

## 3. 你当前最重要的目录

### 3.1 仓库代码目录

核心代码在：

- [D:\code\nanobot\nanobot\nanobot](D:/code/nanobot/nanobot/nanobot)

### 3.2 运行时 workspace

真正的 skill、artifact、workflow 数据不在 repo 里，而在：

- [C:\Users\yuanhao\.nanobot\workspace](C:/Users/yuanhao/.nanobot/workspace)

这里面最重要的是：

- skill：
  - [C:\Users\yuanhao\.nanobot\workspace\skills](C:/Users/yuanhao/.nanobot/workspace/skills)
- artifact：
  - [C:\Users\yuanhao\.nanobot\workspace\artifacts](C:/Users/yuanhao/.nanobot/workspace/artifacts)
- workflow：
  - [C:\Users\yuanhao\.nanobot\workspace\workflows](C:/Users/yuanhao/.nanobot/workspace/workflows)

### 3.3 当前 CAE skill

你现在实际测试的 skill 在：

- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-master-flow-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-master-flow-test/SKILL.md)
- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-cad-stage-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-cad-stage-test/SKILL.md)
- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-mesh-stage-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-mesh-stage-test/SKILL.md)
- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-physics-stage-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-physics-stage-test/SKILL.md)
- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-preprocess-stage-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-preprocess-stage-test/SKILL.md)
- [C:\Users\yuanhao\.nanobot\workspace\skills\cae-postprocess-stage-test\SKILL.md](C:/Users/yuanhao/.nanobot/workspace/skills/cae-postprocess-stage-test/SKILL.md)

### 3.4 当前配置文件

- [C:\Users\yuanhao\.nanobot\config.json](C:/Users/yuanhao/.nanobot/config.json)

这里控制：

- provider / model
- websocket
- gateway
- tools
- CAE guardrail

---

## 4. 第一次学习时，建议先读哪些文件

按下面顺序读。

### 第 1 层：入口层

- [D:\code\nanobot\nanobot\nanobot\cli\commands.py](D:/code/nanobot/nanobot/nanobot/cli/commands.py)
- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py](D:/code/nanobot/nanobot/nanobot/channels/websocket.py)

你要先知道：

- `gateway` 是怎么启动的
- websocket 是怎么接入的
- 用户消息是怎么进入总线的

### 第 2 层：核心编排层

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py](D:/code/nanobot/nanobot/nanobot/agent/loop.py)

这是整个系统最重要的文件，没有之一。

### 第 3 层：LLM 与工具执行层

- [D:\code\nanobot\nanobot\nanobot\agent\runner.py](D:/code/nanobot/nanobot/nanobot/agent/runner.py)
- [D:\code\nanobot\nanobot\nanobot\agent\context.py](D:/code/nanobot/nanobot/nanobot/agent/context.py)
- [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py)

### 第 4 层：subagent 与 workflow 层

- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py](D:/code/nanobot/nanobot/nanobot/agent/subagent.py)
- [D:\code\nanobot\nanobot\nanobot\workflow\store.py](D:/code/nanobot/nanobot/nanobot/workflow/store.py)

### 第 5 层：领域边界控制

- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py)

---

## 5. 运行时主链路该怎么理解

### 5.1 gateway 启动

入口在：

- [D:\code\nanobot\nanobot\nanobot\cli\commands.py:652](D:/code/nanobot/nanobot/nanobot/cli/commands.py:652)

这里是 `_run_gateway()`。

它负责：

- 读配置
- 创建 provider
- 创建 `AgentLoop`
- 启动 channels
- 启动 websocket server

如果系统“根本起不来”，先看这里。

### 5.2 WebSocket 接收消息

WebSocket channel 主体在：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:374](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:374)

启动在：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:876](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:876)

发送在：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:1143](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:1143)

如果 WebUI 有连接问题、收不到消息、消息发不回去，先看这里。

### 5.3 AgentLoop 处理消息

核心入口在：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:579](D:/code/nanobot/nanobot/nanobot/agent/loop.py:579) `run()`
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:654](D:/code/nanobot/nanobot/nanobot/agent/loop.py:654) `_dispatch()`
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788) `_process_message()`

你可以把它理解成：

- `run()`：持续从总线收消息
- `_dispatch()`：给每个 session 串行调度
- `_process_message()`：真正处理一条消息

大多数问题最后都会追到 `_process_message()`。

### 5.4 CAE 过滤模块

接入点在：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273) `_apply_cae_request_filter()`

过滤器本体在：

- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:86](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:86) `CAERequestFilter`
- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:100](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:100) `evaluate()`
- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:218](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:218) `_evaluate_with_llm()`

如果你要看：

- 为什么某条消息被放行
- 为什么某条消息被拦截

就先打这里。

### 5.5 ContextBuilder

消息进入主流程后，会构造 prompt：

- [D:\code\nanobot\nanobot\nanobot\agent\context.py:31](D:/code/nanobot/nanobot/nanobot/agent/context.py:31) `build_system_prompt()`
- [D:\code\nanobot\nanobot\nanobot\agent\context.py:132](D:/code/nanobot/nanobot/nanobot/agent/context.py:132) `build_messages()`

如果你感觉：

- skill 没命中
- prompt 不对
- 历史上下文不对

看这里。

### 5.6 AgentRunner

真正调用模型、执行工具的是：

- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:230](D:/code/nanobot/nanobot/nanobot/agent/runner.py:230) `run()`
- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:666](D:/code/nanobot/nanobot/nanobot/agent/runner.py:666) `_execute_tools()`

如果你要看：

- 为什么模型没调 tool
- 为什么 tool 没执行
- 为什么工具结果没回到模型

看这里。

### 5.7 SpawnTool

subagent 是通过 `spawn` 工具起来的：

- [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:22](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:22)
- [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59) `execute()`

这里也是我们之前修过很多次的点，因为：

- 重复 spawn
- stale active task
- resume 二次 spawn

都和这里强相关。

### 5.8 SubagentManager

子 agent 管理在：

- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:71](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:71)
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:123](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:123) `spawn_task()`
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175) `_run_subagent()`
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:273](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:273) `_announce_result()`
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:388](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:388) `cancel_task()`
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:409](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:409) `is_task_running()`

如果你要看：

- subagent 有没有真正启动
- 为什么启动了但没结果
- 为什么结果回不到主 session
- 为什么取消失败

看这里。

### 5.9 WorkflowStore

workflow 状态持久化在：

- [D:\code\nanobot\nanobot\nanobot\workflow\store.py:13](D:/code/nanobot/nanobot/nanobot/workflow/store.py:13)
- [D:\code\nanobot\nanobot\nanobot\workflow\store.py:23](D:/code/nanobot/nanobot/nanobot/workflow/store.py:23) `create()`
- [D:\code\nanobot\nanobot\nanobot\workflow\store.py:40](D:/code/nanobot/nanobot/nanobot/workflow/store.py:40) `load()`
- [D:\code\nanobot\nanobot\nanobot\workflow\store.py:48](D:/code/nanobot/nanobot/nanobot/workflow/store.py:48) `save()`

如果你要看：

- workflow state 为什么不对
- 为什么重启后状态残留
- 为什么 active workflow 没清掉

看这里和 workspace 里的 `workflows/*.json`。

---

## 6. 最值得打断点的位置

下面是我建议的“第一批断点”。

### 断点组 A：消息有没有进系统

1. [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:1143](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:1143)
2. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:579](D:/code/nanobot/nanobot/nanobot/agent/loop.py:579)
3. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:654](D:/code/nanobot/nanobot/nanobot/agent/loop.py:654)

适合排查：

- WebUI 发了消息但后端没处理
- session key 不对
- follow-up 被路由错了

### 断点组 B：主逻辑入口

1. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788)
2. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)

适合排查：

- 请求为什么被过滤
- 为什么没进入 skill
- 为什么明明是 CAE 请求却被拒

### 断点组 C：workflow/HITL

1. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)
2. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)
3. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1311](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1311)
4. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1210](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1210)

适合排查：

- 子 agent 为什么没正确进入 `needs_user_input`
- 用户回复为什么没恢复 workflow
- pending follow-up 为什么没被吃掉
- workflow 为什么状态错乱

### 断点组 D：subagent

1. [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59)
2. [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:123](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:123)
3. [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175)
4. [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:273](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:273)

适合排查：

- 为什么 spawn 了但实际没起子任务
- 为什么子任务起了但没回结果
- 为什么回调没回到主 session

### 断点组 E：LLM 和工具执行

1. [D:\code\nanobot\nanobot\nanobot\agent\runner.py:230](D:/code/nanobot/nanobot/nanobot/agent/runner.py:230)
2. [D:\code\nanobot\nanobot\nanobot\agent\runner.py:666](D:/code/nanobot/nanobot/nanobot/agent/runner.py:666)
3. [D:\code\nanobot\nanobot\nanobot\agent\context.py:132](D:/code/nanobot/nanobot/nanobot/agent/context.py:132)

适合排查：

- 模型为什么没按预期输出 tool call
- 为什么 tool 执行结果没回进上下文
- prompt 为什么不对

---

## 7. 每个断点该看什么变量

### 7.1 `_process_message()` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788)：

重点看：

- `msg.channel`
- `msg.chat_id`
- `msg.sender_id`
- `msg.content`
- `key`
- `session.key`
- `workflow`
- `raw`

你要先判断：

- 这是普通用户消息
- 还是 system/subagent 消息
- 当前 session 有没有 active workflow

### 7.2 `_apply_cae_request_filter()` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)：

重点看：

- `self.cae_guardrail_config.enable`
- `workflow`
- `decision.action`
- `decision.classifier`
- `decision.category`
- `decision.reason`
- `decision.matched_terms`

如果你觉得“误拦截”或“没拦住”，这里是第一现场。

### 7.3 `_resume_blocked_workflow()` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)：

重点看：

- `workflow.state`
- `workflow.awaiting`
- `workflow.resume_payload`
- `msg.content`
- `workflow.metadata[self._ACTIVE_SUBAGENT_TASK_KEY]`

这里可以直接判断：

- 为什么用户回复没能继续
- 为什么恢复后又重复 spawn

### 7.4 `_handle_structured_subagent_outcome()` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)：

重点看：

- `metadata`
- `subagent_outcome`
- `workflow.workflow_id`
- `workflow.current_stage`
- `workflow.state`
- `subagent_task_id`
- `active_task_id`

如果子 agent 已经回结果，但主流程没动，基本就在这里看。

### 7.5 `spawn.py` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59)：

重点看：

- `arguments`
- `blocked`
- `workflow_id`
- `stage`

如果你怀疑：

- “为什么没 spawn 成功”
- “为什么重复 spawn”

就看 `blocked` 是不是命中了防重复逻辑。

### 7.6 `SubagentManager._run_subagent()` 里重点看

在 [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175)：

重点看：

- `task_id`
- `task_description`
- `target`
- `status`
- `result`

如果子 agent 启动了但行为不对，这里最直接。

---

## 8. 建议的第一轮 debug 路线

第一次学习项目，不要同时开十几个断点。

建议按下面 3 轮来。

### 第一轮：只看一条正常 CAE 请求

目标：

- 看清楚消息如何从 WebUI 进入主流程

只打这几个断点：

1. [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:1143](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:1143)
2. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788)
3. [D:\code\nanobot\nanobot\nanobot\agent\context.py:132](D:/code/nanobot/nanobot/nanobot/agent/context.py:132)
4. [D:\code\nanobot\nanobot\nanobot\agent\runner.py:230](D:/code/nanobot/nanobot/nanobot/agent/runner.py:230)

### 第二轮：只看一次 subagent HITL

目标：

- 看清楚 `spawn -> needs_user_input -> resume`

只打这几个断点：

1. [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59)
2. [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:123](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:123)
3. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)
4. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)

### 第三轮：只看 guardrail

目标：

- 看清楚为什么某条消息被拦或被放

只打：

1. [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)
2. [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:100](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:100)
3. [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:218](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:218)

---

## 9. 常见问题与推荐断点

### 问题 1：WebUI 发了消息，但后端没反应

先看：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:876](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:876)
- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:1143](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:1143)
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:579](D:/code/nanobot/nanobot/nanobot/agent/loop.py:579)

### 问题 2：消息到了，但 skill 没命中

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\context.py:31](D:/code/nanobot/nanobot/nanobot/agent/context.py:31)
- [D:\code\nanobot\nanobot\nanobot\agent\context.py:132](D:/code/nanobot/nanobot/nanobot/agent/context.py:132)
- [C:\Users\yuanhao\.nanobot\workspace\skills](C:/Users/yuanhao/.nanobot/workspace/skills)

### 问题 3：subagent 没启动

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59)
- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:123](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:123)

### 问题 4：subagent 启动了，但没有发起 HITL

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175)
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)
- 当前 skill 的 `SKILL.md`

### 问题 5：用户回复了参数，但 workflow 没恢复

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1311](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1311)

### 问题 6：最终文件没生成

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175)
- [D:\code\nanobot\nanobot\nanobot\workflow\store.py:48](D:/code/nanobot/nanobot/nanobot/workflow/store.py:48)
- [C:\Users\yuanhao\.nanobot\workspace\artifacts](C:/Users/yuanhao/.nanobot/workspace/artifacts)

### 问题 7：guardrail 误杀了 HITL 回复

先看：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)
- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:100](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:100)

---

## 10. 实际调试时建议观察的文件

除了断点，你还应该同步观察两类文件。

### 10.1 workflow 文件

看这里：

- [C:\Users\yuanhao\.nanobot\workspace\workflows](C:/Users/yuanhao/.nanobot/workspace/workflows)

这里能直接看到：

- `state`
- `current_stage`
- `awaiting`
- `resume_payload`
- `metadata.active_subagent_task_id`

这是理解 HITL 状态机最直接的地方。

### 10.2 artifact 文件

看这里：

- [C:\Users\yuanhao\.nanobot\workspace\artifacts](C:/Users/yuanhao/.nanobot/workspace/artifacts)

这里能直接确认：

- 阶段脚本到底有没有生成
- 是子 agent 写的，还是主 agent 在兜底补写

---

## 11. 你现在最推荐的一个练习

如果你要开始真正学这套系统，我建议你做一个最小练习：

### 练习目标

完整看一遍：

- 一条 CAE 主 skill 请求
- 两轮 HITL
- 一个 subagent
- 最终产物生成

### 练习步骤

1. 启动 `nanobot gateway`
2. 打开 WebUI
3. 在以下位置打断点：
   - [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788)
   - [D:\code\nanobot\nanobot\nanobot\agent\tools\spawn.py:59](D:/code/nanobot/nanobot/nanobot/agent/tools/spawn.py:59)
   - [D:\code\nanobot\nanobot\nanobot\agent\subagent.py:175](D:/code/nanobot/nanobot/nanobot/agent/subagent.py:175)
   - [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)
   - [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)
4. 输入一条完整 CAE 测试请求
5. 看 workflow 如何从：
   - `running`
   - 到 `awaiting_user_input`
   - 到 `resuming`
   - 再到完成

只要你把这一条链真的单步走通一次，后面这个项目你就能基本看懂一大半。

---

## 12. 最后建议

### 不要一开始就调“大而全”

最容易失败的方式是：

- WebUI
- guardrail
- master skill
- 5 个 stage
- subagent
- artifact

全部一起调。

你应该每次只看一个问题。

### 调试顺序永远是

1. 消息进来了没有
2. session 对不对
3. workflow 对不对
4. skill 命中了没有
5. subagent 起了没有
6. outcome 回来了没有
7. 文件写了没有

### 先信日志，再信断点

这个项目日志已经很多了。最有效的方式不是“全程断点单步”，而是：

1. 先看日志定位到阶段
2. 再去那个点打断点

这样效率最高。

---

## 13. 一句话总结

如果你要真正学会这个项目，重点不是背所有文件，而是抓住这条主链：

**WebUI / websocket -> AgentLoop -> ContextBuilder -> AgentRunner -> tools/spawn -> SubagentManager -> WorkflowStore -> artifact**

只要你把这条链调明白了，后面的 CAE skill、HITL、guardrail、workflow 都会顺着理解起来。

