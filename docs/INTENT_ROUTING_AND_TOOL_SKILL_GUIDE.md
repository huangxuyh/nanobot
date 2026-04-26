# 意图路由、Tool 体系与 Skill 体系详解

本文档专门讲清楚这几个问题：

1. 这个项目是如何做“意图路由”的
2. 用户一条请求进来后，完整链路是什么
3. tool 体系是什么，skill 体系是什么
4. agent 什么时候选 tool，什么时候选 skill
5. tool 和 skill 会不会冲突
6. 在你当前的 CAE 场景下，这套机制是如何落地的

本文档尽量基于当前仓库和你已经跑过的 WebUI / gateway / CAE skill 场景来讲，不讲抽象空话。

---

## 1. 先给结论

这个项目的“意图路由”不是一个单独的 if-else 路由器，而是**多层协作**：

1. **入口层路由**
   - CLI / WebUI / websocket / API 先把消息送进统一总线
2. **命令路由**
   - `/new`、`/stop` 这类命令先走 `CommandRouter`
3. **领域过滤路由**
   - 例如你现在加的 CAE guardrail，会先决定这条请求能不能继续
4. **上下文路由**
   - `ContextBuilder` 把技能摘要、历史、系统提示拼进 prompt
5. **LLM 决策路由**
   - 模型根据上下文决定：
     - 直接回答
     - 调用某个 tool
     - 命中某个 skill 逻辑
6. **workflow / subagent 路由**
   - 如果命中了 blocking HITL 或多阶段流程，进入 workflow 状态机

所以它不是“传统代码路由表”，而是：

**规则 + 上下文 + LLM + workflow 状态机**  
共同完成的意图路由系统。

---

## 2. 你可以把系统拆成 4 层

### 第 1 层：消息接入层

负责：

- 接受用户输入
- 送入总线
- 把输出返回到前端

典型文件：

- [D:\code\nanobot\nanobot\nanobot\cli\commands.py](D:/code/nanobot/nanobot/nanobot/cli/commands.py)
- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py](D:/code/nanobot/nanobot/nanobot/channels/websocket.py)

### 第 2 层：编排层

负责：

- 会话管理
- 命令分流
- workflow 状态恢复
- skill / subagent 编排

核心文件：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py](D:/code/nanobot/nanobot/nanobot/agent/loop.py)

### 第 3 层：能力层

这里分两块：

- tool：执行动作
- skill：提供任务策略与领域流程

核心文件：

- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py)
- [D:\code\nanobot\nanobot\nanobot\agent\skills.py](D:/code/nanobot/nanobot/nanobot/agent/skills.py)

### 第 4 层：模型决策层

负责：

- 根据上下文判断当前该做什么
- 决定是否调用 tool
- 决定是否按 skill 工作流推进

核心文件：

- [D:\code\nanobot\nanobot\nanobot\agent\context.py](D:/code/nanobot/nanobot/nanobot/agent/context.py)
- [D:\code\nanobot\nanobot\nanobot\agent\runner.py](D:/code/nanobot/nanobot/nanobot/agent/runner.py)

---

## 3. 一条用户请求进来后的完整流程

下面用 WebUI + gateway 的常见路径来讲。

### 第一步：WebUI 把消息发到 websocket

后端 websocket channel 在：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:374](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:374)

启动在：

- [D:\code\nanobot\nanobot\nanobot\channels\websocket.py:876](D:/code/nanobot/nanobot/nanobot/channels/websocket.py:876)

它把前端消息包装成：

- `InboundMessage`

再送进：

- `MessageBus.inbound`

### 第二步：AgentLoop 从总线取消息

主循环在：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:579](D:/code/nanobot/nanobot/nanobot/agent/loop.py:579)

这里做的第一件事不是“立刻问模型”，而是：

1. 看是不是优先级命令
2. 计算 `effective session key`
3. 判断是不是应该进入当前 session 的 pending queue
4. 再决定要不要创建处理 task

### 第三步：进入 `_dispatch()`

在：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:654](D:/code/nanobot/nanobot/nanobot/agent/loop.py:654)

这里做的是：

- 为当前 session 建锁
- 保证同一个 session 串行
- 创建 pending queue
- 真正调用 `_process_message()`

### 第四步：进入 `_process_message()`

在：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:788](D:/code/nanobot/nanobot/nanobot/agent/loop.py:788)

这是整个意图路由的核心现场。

在这里会依次做：

1. system/subagent 消息特殊处理
2. 恢复 session checkpoint
3. slash command 分发
4. 领域过滤（例如 CAE guardrail）
5. active workflow 检查
6. 是否恢复 `awaiting_user_input`
7. 构建 prompt
8. 调用 `AgentRunner`
9. 保存 history
10. 返回 `OutboundMessage`

所以真正意义上的“意图路由”，主要就发生在这里。

---

## 4. 这个项目里的“意图路由”到底是什么

### 4.1 不是单一函数判断“用户想干嘛”

很多人以为“意图路由”就是：

```python
if "mesh" in text:
    ...
elif "physics" in text:
    ...
```

但这个项目不是这种结构。

它的意图路由是多层判断：

### 4.2 第一层：显式命令路由

例如：

- `/new`
- `/stop`

这些不需要 LLM 判断，直接在：

- `CommandRouter`

处理。

### 4.3 第二层：系统边界路由

例如你加的 CAE guardrail：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)
- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:100](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:100)

它先判断：

- 这条请求能不能继续进主流程

也就是说：

- 有些请求在进入 LLM 主逻辑之前就被挡掉了

### 4.4 第三层：workflow 路由

如果当前 session 有 active workflow，且状态是：

- `awaiting_user_input`
- `awaiting_approval`
- `resuming`

那么这条消息并不会走普通问答逻辑，而是进入：

- `_resume_blocked_workflow()`

这也是一种意图路由：

- 系统根据**当前状态**，而不是消息文本本身，决定这条消息的意义

### 4.5 第四层：LLM 路由

如果请求通过了前面几层，并且不在特殊 workflow 状态下，就会进模型。

模型看到的不是裸文本，而是：

- system prompt
- skill 摘要
- 历史消息
- runtime context
- 当前用户输入

然后模型自己决定：

- 直接回答
- 调 tool
- 顺着 skill 工作流继续

---

## 5. skill 体系是什么

### 5.1 skill 本质上不是代码插件

skill 在这个项目里，本质上是：

- 一段结构化 markdown 指令
- 存在 `SKILL.md`
- 被系统作为“能力说明/任务策略”注入到 prompt

也就是说：

**skill 更像是“专门领域的操作说明书”**，而不是 Python 类。

### 5.2 skill 的加载器

skill 加载器在：

- [D:\code\nanobot\nanobot\nanobot\agent\skills.py:21](D:/code/nanobot/nanobot/nanobot/agent/skills.py:21)

当前 skill 目录分两类：

1. workspace skill
2. builtin skill

对应位置：

- workspace：`<workspace>/skills`
- builtin：仓库内置 skills

### 5.3 skill 的发现逻辑

在：

- [D:\code\nanobot\nanobot\nanobot\agent\skills.py:40](D:/code/nanobot/nanobot/nanobot/agent/skills.py:40) `list_skills()`
- [D:\code\nanobot\nanobot\nanobot\agent\skills.py:68](D:/code/nanobot/nanobot/nanobot/agent/skills.py:68) `load_skill()`

一个目录只有在同时满足时才算 skill：

1. 是目录
2. 里面有 `SKILL.md`

### 5.4 skill 如何进入 prompt

不是每次把所有 skill 全文塞进去。

当前更偏向“渐进式加载”：

- 先给模型一个 skill 摘要
- 需要时再读具体 skill 内容

相关逻辑在：

- [D:\code\nanobot\nanobot\nanobot\agent\skills.py:94](D:/code/nanobot/nanobot/nanobot/agent/skills.py:94) `load_skills_for_context()`
- `build_skills_summary()`

### 5.5 skill 在当前 CAE 系统里的作用

你现在的 CAE skill 就是典型例子：

- master skill 负责编排
- stage skill 负责阶段规则和 HITL 字段

skill 定义的是：

- 任务应该怎么拆
- 哪些字段是必须的
- 缺字段时返回什么结构
- 最后应该生成什么文件

skill 本身不执行文件读写和 spawn，真正执行动作还是靠 tool。

---

## 6. tool 体系是什么

### 6.1 tool 本质上是“可执行动作”

和 skill 不同，tool 是真正会执行的动作接口。

例如：

- `read_file`
- `write_file`
- `exec`
- `glob`
- `grep`
- `spawn`

### 6.2 tool 注册中心

在：

- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py:8](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py:8)

核心方法：

- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py:19](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py:19) `register()`
- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py:48](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py:48) `get_definitions()`
- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py:100](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py:100) `execute()`

### 6.3 tool 对模型暴露的方式

tool 会被转成 schema，再作为“可调用函数”暴露给模型。

模型在回答时可以产生：

- tool call request

然后 `AgentRunner` 会去执行这些 tool。

### 6.4 你可以把 tool 理解成“手和脚”

如果说：

- skill 是策略
- prompt 是大脑背景

那 tool 就是：

- 真正动手做事的接口

---

## 7. tool 和 skill 的关系

这是最容易混淆的地方。

### 7.1 一句话区别

**skill 负责告诉 agent“应该怎么做”，tool 负责让 agent“真的做出来”。**

### 7.2 skill 负责什么

skill 负责：

- 定义任务流程
- 定义阶段顺序
- 定义 HITL 规则
- 定义缺失字段
- 定义产物要求

例如你的 CAE master skill 会规定：

- 如果从头跑，就按 `cad -> mesh -> physics -> preprocess -> postprocess`
- 如果给了 `script_path`，先判断 `COMPLETED_STAGES`

### 7.3 tool 负责什么

tool 负责：

- 读脚本
- 写脚本
- 执行命令
- 调子 agent

例如：

- `read_file` 去读 `cad_mesh_done.py`
- `spawn` 去启动 `cae-physics-stage-test`
- `write_file` 去写 `03_physics_stage.py`

### 7.4 它们会冲突吗

正常情况下**不冲突**，因为职责不同。

可以理解成：

- skill 是“做菜菜谱”
- tool 是“刀、锅、灶台”

冲突只会出现在以下两种情况：

1. skill 设计得太强，要求 agent 做一堆步骤，但工具能力不够
2. agent 没按 skill 策略走，直接乱用 tool

你前面调试过程中看到的很多问题，其实就是第二类：

- 子 agent 没按 skill 正确返回 `needs_user_input`
- 主 agent 自己补写了文件
- skill 想让 subagent 完成，最后变成 main agent 兜底

这不是 tool 和 skill 概念冲突，而是：

**实际执行没有完全服从 skill 约束。**

---

## 8. agent 到底什么时候选 tool

### 8.1 当模型认为“需要执行动作”时

一旦模型认为单靠文字回答不够，就会调 tool。

常见情况：

- 需要读取文件
- 需要写文件
- 需要搜索 workspace
- 需要执行 shell
- 需要启动 subagent

### 8.2 典型例子

用户说：

```text
请从 cad_mesh_done.py 继续完成后面的 CAE 流程
```

模型一般会先：

1. 调 `read_file`
2. 解析 `COMPLETED_STAGES`
3. 再决定是否 `spawn`

### 8.3 tool 的选择发生在 AgentRunner 循环里

主循环在：

- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:230](D:/code/nanobot/nanobot/nanobot/agent/runner.py:230)

执行工具在：

- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:666](D:/code/nanobot/nanobot/nanobot/agent/runner.py:666)

也就是说：

1. 模型先返回一个或多个 tool call
2. `AgentRunner` 执行
3. tool result 再回到消息上下文
4. 模型继续下一步

---

## 9. agent 到底什么时候选 skill

### 9.1 skill 不是“像 tool 一样被调用”

这是关键区别。

tool 是模型显式产出 function call 去调用的。

skill 不是这样。skill 更像：

- 模型当前任务的操作框架
- 被加载进上下文后影响模型决策

### 9.2 skill 的触发本质上靠上下文命中

主要有几种触发方式：

1. 用户显式提到 skill 名
   - 例如 `$cae-master-flow-test`
2. system / context 中已经注入了相关 skill 摘要
3. 模型从任务描述中理解到某个 skill 明显更匹配

### 9.3 所以“选 skill”更像“选工作模式”

举例：

用户说：

```text
请严格按 $cae-master-flow-test 执行
```

这不是 tool call。

而是模型在后续推理时会：

- 把 `cae-master-flow-test` 当作当前工作模式
- 按 skill 指令做：
  - 先问 `project_name`
  - 再 `spawn` 子 skill
  - 再生成产物

也就是说：

**skill 决定“如何思考”，tool 决定“如何动作”。**

---

## 10. 一个完整 CAE 请求到底怎么走

下面用你当前最典型的例子来串起来。

### 用户输入

```text
请严格按 $cae-master-flow-test 执行。我需要从头完成一个 CAE 流程。
```

### 步骤 1：消息进入 AgentLoop

- websocket 收到消息
- `MessageBus` 入队
- `AgentLoop.run()` 消费

### 步骤 2：命令与 guardrail

在 `_process_message()`：

- 不是 slash command
- CAE guardrail 判断：
  - 这是 CAE 请求，允许

### 步骤 3：构建 prompt

`ContextBuilder` 把这些拼给模型：

- system prompt
- 历史消息
- skill 摘要
- 当前输入

### 步骤 4：模型决定按 master skill 工作

因为用户显式提到了：

- `$cae-master-flow-test`

所以模型会按这个 skill 逻辑思考。

### 步骤 5：模型先调用 tool

例如先：

- `read_file` 读样例脚本
- `spawn` 启动 `cae-cad-stage-test`

这里能看出：

- **技能在指导流程**
- **工具在完成动作**

### 步骤 6：subagent 返回 `needs_user_input`

`SubagentManager` 跑 CAD 子 skill，发现缺第一轮参数，于是通过 structured outcome 回来：

```json
{
  "status": "needs_user_input",
  ...
}
```

### 步骤 7：workflow 进入阻断状态

`AgentLoop._handle_structured_subagent_outcome()` 会把 workflow 改成：

- `awaiting_user_input`

### 步骤 8：用户回复参数

用户输入：

```text
cad_model_name: cantilever-beam
cad_geometry_summary: 一端固定一端自由的矩形悬臂梁
```

### 步骤 9：workflow 恢复

这次 `_process_message()` 不再走普通问答，而是走：

- `_resume_blocked_workflow()`

然后继续 spawn 恢复任务。

### 步骤 10：最终写文件

当子 skill 完成后：

- `write_file` 生成 `01_cad_stage.py`
- 然后主 skill 继续下一个阶段

最后生成：

- `final_cae_workflow.py`

---

## 11. 为什么说这个项目的路由核心在 AgentLoop，而不是 skill

很多人会误以为：

- skill 是项目的主控器

其实不是。

真正的主控器还是：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py](D:/code/nanobot/nanobot/nanobot/agent/loop.py)

原因是：

### 11.1 skill 不能直接控制消息生命周期

skill 只能影响模型如何理解任务，但不能直接控制：

- session 锁
- pending queue
- workflow 恢复
- outbound message

### 11.2 skill 不能直接执行工具

skill 只是说明书，真正执行 tool 的还是：

- `AgentRunner`
- `ToolRegistry`

### 11.3 workflow 也不是 skill 的一部分

workflow 是代码层状态机，不是 markdown 层。

所以从“系统工程”的角度看：

- skill 是行为策略层
- AgentLoop 是执行编排层

---

## 12. 常见误解

### 误解 1：skill 会自动执行

不会。

skill 必须先被命中、加载进上下文，然后由模型按 skill 内容决定下一步。

### 误解 2：tool 和 skill 是替代关系

不是。

它们是互补关系：

- skill = 策略
- tool = 动作

### 误解 3：有了 skill 就不需要 prompt

不对。

skill 本身最终还是靠 prompt 注入影响模型。

### 误解 4：用户一提 skill，系统就一定严格执行

也不绝对。

如果 skill 写得不够硬，或者上下文冲突，模型还是可能偏离。  
这也是为什么你前面一直在做：

- blocking HITL
- subagent 单活控制
- guardrail

这些代码级约束。

---

## 13. 如果你要 debug 意图路由，该从哪里下断点

### 13.1 想看“这条请求为什么被挡住了”

看：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1273](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1273)
- [D:\code\nanobot\nanobot\nanobot\agent\guardrails\cae_filter.py:100](D:/code/nanobot/nanobot/nanobot/agent/guardrails/cae_filter.py:100)

### 13.2 想看“为什么没命中 skill”

看：

- [D:\code\nanobot\nanobot\nanobot\agent\context.py:31](D:/code/nanobot/nanobot/nanobot/agent/context.py:31)
- [D:\code\nanobot\nanobot\nanobot\agent\context.py:132](D:/code/nanobot/nanobot/nanobot/agent/context.py:132)
- [D:\code\nanobot\nanobot\nanobot\agent\skills.py](D:/code/nanobot/nanobot/nanobot/agent/skills.py)

### 13.3 想看“为什么选了这个 tool”

看：

- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:230](D:/code/nanobot/nanobot/nanobot/agent/runner.py:230)
- [D:\code\nanobot\nanobot\nanobot\agent\runner.py:666](D:/code/nanobot/nanobot/nanobot/agent/runner.py:666)
- [D:\code\nanobot\nanobot\nanobot\agent\tools\registry.py:100](D:/code/nanobot/nanobot/nanobot/agent/tools/registry.py:100)

### 13.4 想看“为什么 workflow 没恢复”

看：

- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1499](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1499)
- [D:\code\nanobot\nanobot\nanobot\agent\loop.py:1606](D:/code/nanobot/nanobot/nanobot/agent/loop.py:1606)

---

## 14. 最后给你的一个简化记忆法

如果你要用一句话记住这个项目：

**AgentLoop 是总调度，skill 决定策略，tool 完成动作，runner 执行循环，workflow 管理阻断状态。**

再压缩一点：

**skill 决定“怎么做”，tool 决定“做什么动作”，AgentLoop 决定“现在该走哪条路”。**

---

## 15. 一句话总结

这个项目的意图路由不是单点路由，而是：

**命令路由 + 领域过滤 + workflow 状态路由 + skill 上下文驱动 + tool 调用决策**  
共同组成的一套执行系统。

在这套系统里：

- **skill 不负责执行**
- **tool 不负责规划**
- **AgentLoop 才是总入口和总编排者**

