# nanobot Subagent 为什么没有 HITL / “HITP” 机制

本文档专门回答一个问题：

**为什么当前 `nanobot` 的 `subagent` 没有直接的 Human-in-the-Loop（HITL）能力？**

你在问题里写的是 “HITP”。从上下文看，这里讨论的实际上是：

- 子 Agent 在执行过程中是否能直接向用户追问
- 是否能直接请求用户确认/授权
- 是否能在等待用户回复后由子 Agent 自己继续执行

本文统一按 **HITL** 来分析。如果你后续对 “HITP” 有更具体定义，也可以再单独扩展。

---

## 1. 结论先说

当前项目里：

- **主 Agent 支持会话式 HITL**
- **subagent 不支持直接 HITL**

这不是“忘了做”，而是一个**刻意的架构边界**。

当前设计下，subagent 的职责是：

- 在后台独立执行一个任务
- 把结果回传给主 Agent
- 由主 Agent 再决定是否和用户交互

也就是说，当前系统采用的是：

**Main Agent = 唯一用户交互入口**  
**Subagent = 后台 worker / delegate**

所以不是：

- 用户 ↔ 主 Agent ↔ 子 Agent 都能直接互相对话

而是：

- 用户 ↔ 主 Agent ↔ subagent

其中 human-in-the-loop 只发生在主 Agent 这一层。

---

## 2. 代码层面的直接证据

### 2.1 主 Agent 有 `message` 工具，subagent 没有

主 Agent 在 `AgentLoop._register_default_tools()` 中注册了：

- `MessageTool`
- `SpawnTool`

对应代码：

- `nanobot/agent/loop.py`

这意味着主 Agent 既可以：

- 直接向用户发消息
- 继续派生子任务

而 subagent 在 `SubagentManager._run_subagent()` 里构造工具集时，代码注释写得非常明确：

- `# Build subagent tools (no message tool, no spawn tool)`

subagent 只拿到：

- 文件工具
- 搜索工具
- shell 工具
- web 工具

但没有：

- `message`
- `spawn`

对应代码：

- `nanobot/agent/subagent.py`

这条约束本身就已经说明：

**当前架构不允许子 Agent 直接触达用户，也不允许子 Agent 自己继续分裂任务树。**

---

### 2.2 subagent 的 prompt 也明确把它定义成后台执行者

`nanobot/templates/agent/subagent_system.md` 里写得很清楚：

- 你是被主 Agent 派生出来完成一个具体任务的
- 你的最终结果会被回报给主 Agent

这个 prompt 的重点不是：

- “你可以自己和用户协商”

而是：

- “Stay focused on the assigned task”
- “Your final response will be reported back to the main agent”

这说明产品定位上，subagent 被定义成：

**执行型角色**

而不是：

**交互型角色**

---

### 2.3 subagent 的结果回流方式是“系统消息回主 Agent”

subagent 完成后不是直接回用户，而是调用 `_announce_result(...)`：

1. 渲染 `subagent_announce.md`
2. 构造 `InboundMessage(channel="system", sender_id="subagent", ...)`
3. 发布到 `MessageBus`
4. 让主 Agent 再处理一轮

这说明：

subagent 和用户之间没有直接消息通道，subagent 的唯一出口是：

**回到主 Agent**

这又进一步证明，当前设计故意保持了“单一用户交互代理”的结构。

---

## 3. 为什么系统会这样设计

这部分是最重要的。当前设计并不是功能缺失，而是明显在追求几个架构目标。

---

## 4. 设计原因一：保持单一用户交互入口

如果 subagent 也能直接对用户发问，会立刻引入一个复杂问题：

**到底谁代表系统和用户说话？**

如果只有主 Agent 可以和用户对话，那么：

- 用户只需要理解一个对话主体
- 所有追问、确认、补充都回到同一条主会话
- Session、权限、历史、恢复逻辑都集中在主 Agent 层

如果 subagent 也能直接发问，就会出现这些问题：

- 用户看到的是主 Agent 还是子 Agent 在说话？
- 多个 subagent 同时发问怎么办？
- 用户回复一句话时，这句话属于哪个 subagent？
- 如果用户回答模糊，谁来做总线仲裁？

当前设计通过“只允许主 Agent 对人类说话”直接规避了这些复杂性。

这是非常典型、也非常合理的架构取舍。

---

## 5. 设计原因二：避免并发人机交互把会话搞乱

主 Agent 当前已经有一套相对复杂但可控的 HITL 机制：

- session 历史
- pending queue
- mid-turn injection
- checkpoint 恢复

这些机制都默认：

- 一个 session 只有一个“前台交互主体”

如果 subagent 也可以直接 HITL，就意味着系统要支持：

- 一个 session 下多个执行体并发等待用户
- 多个等待点同时争抢用户回复
- 将用户回复精确路由到正确的等待实体

当前项目并没有：

- approval token
- waiting handle
- suspended execution frame
- explicit interaction id

这些能力。

所以如果贸然让 subagent 直接 HITL，最可能出现的不是“更强大”，而是：

- 用户回复被路由错
- 子任务间交叉污染
- 会话状态变得不可解释

从当前代码基础看，设计者显然优先选择了：

**限制 subagent 的交互能力，换取主会话的一致性。**

---

## 6. 设计原因三：让 subagent 保持“后台 worker”角色纯度

当前 subagent 的角色非常清晰：

- 接受一个任务
- 自己用工具完成
- 返回结果或失败摘要

这种设计有几个工程上的优点。

### 6.1 它更容易推理

subagent 的职责只有“执行任务”，而不是：

- 执行任务
- 自己决定什么时候问人
- 自己等待用户
- 自己恢复执行

一个职责越单一，越容易被预测和调试。

### 6.2 它更容易失败收敛

当前 subagent 开启了：

- `fail_on_tool_error=True`
- `max_iterations=15`

这说明它更像是一个受限 worker。

如果把人类交互也塞进去，它的生命周期就会大幅拉长，失败形态也会变复杂：

- 是执行失败？
- 是在等人？
- 是用户拒绝了？
- 是用户没回？
- 是等错人了？

这些都不是当前 subagent 设计想承担的复杂度。

### 6.3 它更利于资源管理

当前 subagent 是短生命周期后台任务，完成后会清理：

- `_running_tasks`
- `_task_statuses`
- `_session_tasks`

如果 subagent 进入“等待用户回复”状态，它就不再是一个短生命周期 worker，而会变成：

- 半持久交互实体

这会要求新的资源模型、超时模型、恢复模型和清理模型。

当前设计明显不想在 subagent 层引入这类状态爆炸。

---

## 7. 设计原因四：安全边界更清晰

从安全角度看，当前系统的用户触达权限被集中在主 Agent 的 `message` 工具上。

这带来两个好处：

### 7.1 用户沟通可被统一约束

所有对用户说的话，都天然经过主 Agent 层。

如果后续要增加：

- 审计
- 统一模板
- 风险提示
- 授权确认规范

都可以在主 Agent 层做。

### 7.2 子 Agent 不会绕过主 Agent 直接触达用户

如果 subagent 能直接发消息，它就可能：

- 在上下文不完整时错误追问
- 在未被审核的情况下请求敏感授权
- 直接暴露过多底层细节

当前设计通过彻底拿掉 `message` 工具，把这个风险面直接关掉了。

---

## 8. 当前设计的代价是什么

架构取舍一定有代价。

当前 subagent 没有 HITL，也会带来几个明显局限。

### 8.1 子任务遇到缺参时不能原地追问

例如 subagent 做 CAE 网格时发现：

- 缺少 `mesh_size`
- 缺少边界条件

它不能直接问用户。

只能：

1. 返回失败或返回“需要更多输入”的结果
2. 主 Agent 接收到结果
3. 主 Agent 再去问用户
4. 用户回复后，主 Agent 再决定是否重启该 subagent

这比“子 Agent 自己问了再继续”要绕一层。

### 8.2 不能形成真正的长生命周期子流程

有些复杂工程任务天然是：

- 执行一部分
- 等人工确认
- 再执行下一部分

当前 subagent 不适合承载这种流程。

### 8.3 不能把用户授权和子任务执行紧密绑定

例如你想实现：

- CAD 子任务生成网格脚本
- 直接向用户请求“批准执行脚本”
- 用户批准后原地继续

当前架构下做不到“原地继续”，只能回到主 Agent 再调度。

---

## 9. 这种设计是否合理

从当前项目定位看，我认为它是**合理的**。

原因很简单：

这个项目当前不是一个多代理审批工作流系统，而是一个：

- 单前台 Agent
- 多后台 worker

的工具型运行时。

在这种定位下：

- 主 Agent 管交互
- subagent 管执行

是最稳定、最容易维护的方案。

如果一开始就让 subagent 也具备完整 HITL，系统复杂度会明显上升，而且会立刻要求补齐很多现在并没有的基础设施：

- interaction id
- waiting state
- approval token
- user reply routing
- suspended task recovery
- timeout / escalation policy

在这些能力都还没有的时候，限制 subagent 直接 HITL 是一个保守但正确的工程选择。

---

## 10. 是否建议添加这个机制

答案不是简单的“是”或“否”，而是：

**建议，但不建议直接把完整 HITL 生硬塞进当前 subagent。**

应该分阶段。

---

## 11. 不建议的做法

最不建议的做法是：

- 直接给 subagent 注册 `message` 工具
- 让 subagent 自己向用户发问
- 其余 routing / state / approval 啥都不改

这样短期看似“功能打通了”，实际会埋下很多问题：

- 多个 subagent 并发追问用户
- 用户回复不知道该进哪个执行体
- 主 Agent 和 subagent 对同一用户争抢对话主导权
- 历史恢复逻辑变得混乱
- UI/渠道层无法表达“这是哪个后台任务的追问”

这会把当前相对清晰的主从结构打乱。

---

## 12. 更建议的演进路径

如果你确实需要 subagent 也参与 HITL，我建议按以下顺序演进。

### 方案 A：保持主 Agent 为唯一人机接口，不给 subagent 直接对话权

这是我最推荐的短中期方案。

做法是让 subagent 返回结构化结果，例如：

```json
{
  "status": "needs_user_input",
  "reason": "missing_mesh_size",
  "question": "请提供网格尺寸，例如 2mm。",
  "required_fields": ["mesh_size"],
  "resume_payload": {
    "stage": "mesh",
    "task_id": "abc123"
  }
}
```

然后由主 Agent：

1. 向用户提问
2. 接收用户回复
3. 把回复和 `resume_payload` 一起重新交给 subagent，或重启一个新 subagent

这种方式的优点是：

- 对用户来说，仍然只有主 Agent 在说话
- 对架构来说，不破坏当前单入口设计
- 对实现来说，只需要增强“结构化返回”和“恢复协议”

它本质上是：

**Subagent 提出 HITL 请求，Main Agent 代理完成 HITL。**

这是最稳妥的路线。

---

### 方案 B：为 subagent 增加“请求用户输入”的能力，但不直接发消息

可以考虑给 subagent 增加一个内部工具，例如：

- `request_user_input`
- `request_approval`

但这个工具的行为不是直接发消息，而是：

1. 生成一个结构化请求对象
2. 交回主 Agent 或运行时
3. 由主 Agent 决定如何发给用户
4. 用户回复后由系统恢复执行

这比直接开放 `message` 工具好很多，因为它保留了：

- 人机交互统一出口
- 子任务的结构化等待意图

这是一个比较干净的中期方案。

---

### 方案 C：真正让 subagent 具备直接 HITL

只有当你明确要构建：

- 多代理协作系统
- 子流程级审批
- 复杂工程编排

时，才建议走这一步。

但一旦这样做，你必须同时新增这些基础能力：

1. **Interaction ID**
   每次子 Agent 发出的追问都必须带唯一交互标识

2. **Waiting State**
   subagent 必须能进入 `awaiting_user_input` / `awaiting_approval`

3. **Reply Routing**
   用户回复必须能被精确路由到对应 subagent，而不是只回主 session

4. **Suspended Execution Frame**
   等待用户期间，subagent 不能只是“结束”，而要能挂起并恢复

5. **Timeout / Escalation**
   用户不回时怎么办？转主 Agent？自动取消？继续提醒？

6. **Concurrency Policy**
   多个 subagent 同时等待用户时，系统如何限制和排序？

7. **UI / Channel Semantics**
   用户端是否要显式展示“这是某个后台任务的提问”？

如果这些都不做，直接放开 subagent 对用户说话，风险很高。

---

## 13. 我对是否要加的实际建议

### 如果你的目标是当前项目继续保持“通用工具 Agent”

建议：

- **不要让 subagent 直接拥有完整 HITL**
- 保持主 Agent 是唯一用户接口
- 增强 subagent 的结构化返回，让它能表达“我需要用户输入/授权”

这是最平衡的路线。

### 如果你的目标是做 CAE / 仿真 / 多阶段工程代理

建议：

- **加，但先加“代理式 HITL”，不要先加“直连式 HITL”**

也就是：

- subagent 发现需要人工
- subagent 返回 `needs_user_input` / `needs_approval`
- 主 Agent 统一提问
- 用户回复后主 Agent 再恢复该子流程

这是最适合工程场景的做法。

### 只有在下面条件都成立时，才建议让 subagent 直接 HITL

- 你已经有明确的多代理交互产品形态
- 你愿意引入更复杂的状态机
- 你准备重构消息路由和恢复机制
- 你需要“子流程自己问、自己等、自己恢复”的强能力

否则不建议一步到位。

---

## 14. 一个推荐的目标架构

如果你未来真的想演进，我建议目标不是：

- “subagent 直接拿到 `message` 工具”

而是下面这种：

```text
User
  |
  v
Main Agent
  |
  +-- spawn --> Subagent A
  |               |
  |               +-- returns: needs_user_input(question, schema, resume_token)
  |
  +-- asks user
  |
  +-- receives user reply
  |
  +-- resume_subagent(resume_token, user_payload)
```

这个架构的核心思想是：

- subagent 可以“提出 HITL 请求”
- 但不直接成为用户交互主体

这样既保留主 Agent 的单一用户入口，又能让子流程在逻辑上拥有等待人工的能力。

---

## 15. 推荐的新增能力列表

如果你要往这个方向落地，我建议优先新增：

### 15.1 `SubagentResult` 结构化协议

至少支持：

- `ok`
- `error`
- `needs_user_input`
- `needs_approval`

### 15.2 `resume_token`

用于标识某个被挂起的子流程。

### 15.3 `resume_subagent(...)`

允许主 Agent 在拿到用户输入后恢复或重建子流程。

### 15.4 主 Agent 层的 Approval / Input Manager

统一负责：

- 向用户提问
- 等待回复
- 解析回复
- 恢复执行

### 15.5 交互审计

记录：

- 谁发起了哪次用户确认
- 用户怎么回复
- 最终恢复到了哪个执行步骤

---

## 16. 一句话总结

`nanobot` 当前的 subagent 没有 HITL，并不是缺陷，而是为了维持下面这个清晰边界：

**主 Agent 负责和人说话，subagent 负责在后台做事。**

这个设计在当前阶段是合理的，也更稳。

如果你想增强它，我建议：

- **先加“subagent 请求 HITL，main agent 代理完成 HITL”**
- **不要直接让 subagent 获得完整用户交互权**

只有当你准备把系统升级为真正的多代理交互编排平台时，才值得引入“subagent 直接 HITL”。
