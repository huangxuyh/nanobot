# 基于当前 nanobot 架构，CAE Agent 是否需要给 Subagent 增加“完全独立 HITL”

本文档基于当前仓库实现和你描述的 CAE 目标场景，分析一个核心问题：

**如果要基于 `nanobot` 开发一个 CAE Agent，是否需要让 `subagent` 也具备“完全独立的 Human-in-the-Loop（HITL）能力”？**

你当前的设计前提是：

- `cad`
- `网格`
- `前处理`
- `后处理`

都拆成独立 skill。

这样做的原因也很合理：

- 不想把一个总的 `cae skill` 写得过于臃肿
- 每个子 skill 自己已经足够复杂
- 每个子 skill 在实际执行时都可能反复和用户沟通

这正是一个典型的“多阶段、多专家技能、多轮补充输入”的工程代理场景。

---

## 1. 结论先说

我的结论是：

**现阶段不建议你直接给 subagent 做“完全独立 HITL”。**

更推荐的路线是：

**主 Agent 持有唯一用户交互权，subagent 只负责执行和返回结构化的人类介入请求。**

也就是说，不建议你一上来做：

- `subagent` 自己直接问用户
- `subagent` 自己等待用户回复
- `subagent` 自己基于回复恢复执行

而建议你先做：

- `subagent` 返回 `needs_user_input`
- 或返回 `needs_approval`
- 主 Agent 统一向用户提问
- 用户回复后，主 Agent 再恢复或重建相应子流程

一句话总结：

**你需要的是“Subagent 可请求 HITL”，但未必需要“Subagent 自己独立完成 HITL”。**

---

## 2. 为什么这是当前更合理的结论

因为你的问题不是简单的“子任务是否复杂”，而是：

**复杂子任务的人机交互，应该落在哪一层？**

从当前 `nanobot` 架构看，交互层和执行层本来就是分开的：

- Main Agent：对用户、对会话、对 session、对 pending queue、对恢复负责
- Subagent：后台 worker，负责独立完成一个任务并回报结果

当前项目已经明确是：

- 主 Agent 有 `message` 工具
- subagent 没有 `message` 工具
- subagent 的结果通过 system message 回到主 Agent

这说明当前仓库的天然设计就是：

**Main Agent = orchestration + HITL**  
**Subagent = execution delegate**

这套边界在 CAE 场景里依然成立，而且其实比“所有层都能跟用户说话”更稳。

---

## 3. 你当前 CAE 场景的真实需求，拆开后是什么

你描述的需求，表面上像是在说：

> 每个 skill 都很复杂，都可能反复问用户，所以 subagent 似乎也应该直接具备独立 HITL。

但把它拆开后，真正的需求其实有 4 类。

### 3.1 技能粒度需要拆开

这个需求是合理的，而且我赞同。

如果把这些内容全塞到一个 `cae skill`：

- skill 会变得过大
- 触发描述会混乱
- 模型选择/加载成本会升高
- 维护成本会很高

所以把 `cad` / `mesh` / `preprocess` / `postprocess` 拆成独立 skill，是正确方向。

### 3.2 每个阶段都可能缺参数

例如：

- CAD 阶段缺几何来源、尺寸规则、导入格式
- 网格阶段缺网格尺寸、单元类型、质量阈值
- 前处理阶段缺材料、边界条件、载荷
- 后处理阶段缺结果指标、截面、报告格式

这意味着系统必须具备强多轮交互能力。

### 3.3 每个阶段都可能需要确认

例如：

- 是否覆盖已有模型
- 是否执行脚本
- 是否提交仿真
- 是否采用自动修复网格

这意味着不仅要补参数，还要做审批/确认。

### 3.4 每个阶段内部都可能是长流程

例如网格阶段未必是一个函数，而可能是：

1. 读模型
2. 分析几何复杂性
3. 选择网格策略
4. 试一次网格
5. 发现质量差
6. 调整
7. 再输出

这会让你自然觉得：

“既然每个阶段自己都是一个小世界，那 subagent 好像也应该自己和用户来回沟通。”

但这只是一个表象，不一定意味着“独立 HITL”是最优解。

---

## 4. 为什么“不一定需要 subagent 完全独立 HITL”

因为“阶段复杂”不等于“阶段必须自己拥有对话权”。

这是两个不同问题。

### 4.1 复杂执行 ≠ 复杂交互归属

一个子流程很复杂，只能说明：

- 它需要独立上下文
- 它需要独立技能
- 它需要独立执行逻辑

但不自动推出：

- 它一定需要自己直接跟用户说话

在很多工业系统里，恰恰相反：

- 执行单元越复杂
- 越不让它直接面对用户
- 而是通过 orchestrator 统一代理人机交互

原因是这样更容易：

- 审计
- 回滚
- 路由
- 恢复
- 控制并发

### 4.2 CAE 场景的人类输入，很多本质上属于“全局流程输入”

比如：

- 材料
- 边界条件
- 单位制
- 解算目标
- 输出格式

这些信息虽然会在某个具体阶段暴露为“缺失”，但它们并不完全属于那个阶段私有。

它们更像：

- 整个 CAE 流程的全局约束

所以把它们收束在主 Agent 层统一问和统一记录，通常比让某个 subagent 自己问要更稳。

### 4.3 你现在更需要的是“强 Slot Filling + 强 Planner”，不是“子 Agent 自治对话”

从仓库里已有的 CAE 文档方向也能看出这个思路：

- `CAESkillSelector`
- `CAESlotFillingManager`
- `CAEPlanner`

这些建议新增的能力，说明作者自己对 CAE 的工程化想法也是：

- 先把流程、参数、计划显式化
- 再让工具执行

而不是：

- 让一堆 subagent 各自和用户自由来回协商

对 CAE 这种强顺序、强依赖、强参数约束的系统来说：

**工程控制层比多主体自由对话层更重要。**

---

## 5. 直接给 subagent 完整独立 HITL，会带来什么问题

如果你真的让每个阶段 subagent 都能自己问用户、自己等回复、自己恢复，会引入一整套新复杂度。

### 5.1 用户会面对多个“说话主体”

这会立刻带来认知问题：

- 现在是谁在问我？
- 是总控 CAE Agent 还是 mesh agent？
- CAD agent 和后处理 agent 可以同时问吗？
- 我回复这句“继续”，到底是在回答谁？

对用户来说，这会让系统更像一个嘈杂的多线程群聊，而不是一个可靠工程助手。

### 5.2 多个等待点的回复路由会非常难

当前 `nanobot` 的 HITL 能力主要绑定在：

- session
- pending queue
- mid-turn injection

这套机制默认只有一个前台交互主体。

如果 subagent 也独立 HITL，就必须解决：

- 一个 session 下多个等待中的子流程
- 用户回复怎样精确路由到正确 subagent
- 是否需要 interaction id
- 是否需要 UI 上显式呈现“你在回答哪个问题”

这些能力当前仓库没有现成实现。

### 5.3 你会被迫把 subagent 从“短生命周期 worker”改成“半持久交互实体”

当前 subagent 是短生命周期后台任务。

如果它要等待用户，就必须新增：

- waiting state
- suspended frame
- resume token
- timeout policy
- cleanup policy
- rehydration policy

这会从根本上改变 subagent 的角色。

### 5.4 你会把当前最难的问题前置

对 CAE Agent 来说，当前最难的问题通常不是：

- subagent 能不能说话

而是：

- 意图分类
- 参数完整性
- 流程规划
- 执行顺序
- 错误恢复
- 结果解释

如果你过早把精力投入到“subagent 独立 HITL”，很可能会把核心工程问题往后推。

---

## 6. 那为什么你仍然会直觉上觉得“需要它”

因为你的直觉抓住了一个真实问题：

**每个 CAE 子阶段和用户之间，确实存在高频、强依赖的人机往返。**

这个判断是对的。

真正需要修正的不是问题判断，而是解决路径。

你需要的不是：

- “让 subagent 直接和用户说话”

而更可能是：

- “让 subagent 能非常明确地告诉主 Agent：现在我缺什么、为什么缺、该怎么问用户、拿到什么后如何恢复”

这两种能力外观看起来相似，工程代价却差很多。

---

## 7. 更适合 CAE 的推荐架构

我建议你把系统分成 4 层。

### 7.1 Main Agent / CAE Orchestrator 层

职责：

- 对用户唯一说话
- 统一做 session 级 HITL
- 统一维护当前总任务状态
- 统一决定当前进入哪个子阶段

这层是唯一用户接口。

### 7.2 CAE Planning 层

职责：

- `CAEIntentClassifier`
- `CAESkillSelector`
- `CAESlotFillingManager`
- `CAEPlanner`

这层负责：

- 判断要做哪类 CAE 任务
- 需要哪些参数
- 哪些参数还缺
- 当前应该进入哪个 skill / 阶段

### 7.3 Subagent / Worker 层

职责：

- 执行 `cad` / `mesh` / `preprocess` / `postprocess`
- 使用局部 skill、局部工具、局部脚本
- 在发现缺失信息时，返回结构化请求，而不是直接问用户

### 7.4 Tool / Executor 层

职责：

- 真实调用 CAD/网格/仿真/后处理工具
- 执行脚本
- 校验结果
- 输出产物

---

## 8. 你真正应该给 subagent 增加的，不是“完整独立 HITL”，而是这三类能力

### 8.1 结构化的 `needs_user_input`

例如：

```json
{
  "status": "needs_user_input",
  "stage": "mesh",
  "reason": "missing_mesh_size",
  "question": "请提供网格尺寸，例如 2mm 或 5mm。",
  "required_fields": ["mesh_size"],
  "context_summary": "当前几何已导入，网格策略已确定，但缺少目标尺寸。",
  "resume_payload": {
    "skill": "mesh",
    "stage_id": "mesh_01",
    "artifact": "workspace/case/model.step"
  }
}
```

### 8.2 结构化的 `needs_approval`

例如：

```json
{
  "status": "needs_approval",
  "stage": "preprocess",
  "approval_type": "run_script",
  "question": "即将执行网格修复脚本，是否继续？",
  "risk_level": "medium",
  "proposed_action": "run cae_mesh_repair.py",
  "resume_payload": {
    "skill": "preprocess",
    "stage_id": "prep_03"
  }
}
```

### 8.3 明确的 `resume_payload`

也就是：

- subagent 自己不等待
- 但要能准确告诉主 Agent
- 用户补完后应该如何恢复

这是最关键的工程能力。

---

## 9. 为什么这种方案比“subagent 完整独立 HITL”更适合你当前阶段

### 9.1 它保留了 skill 的拆分优势

你仍然可以：

- 把 `cad` / `mesh` / `preprocess` / `postprocess` 分开
- 每个 skill 内部保持专业复杂度
- 每个 subagent 有独立局部上下文

### 9.2 它避免了多交互主体混乱

所有用户问题仍然只从主 Agent 发出。

### 9.3 它更容易做参数治理

主 Agent 层可以统一维护：

- 当前已知参数
- 缺失参数
- 参数来源
- 用户最近一次确认

这比让多个 subagent 各自维护一套会话输入要稳定得多。

### 9.4 它更容易恢复和审计

你可以很清楚地记录：

- 哪个 subagent 提出了什么请求
- 主 Agent 怎么问用户
- 用户怎么回答
- 用这个回答恢复了哪个阶段

这对工程代理非常重要。

---

## 10. 那什么时候才真的需要“subagent 完全独立 HITL”

只有在下面这些条件同时成立时，我才会建议你认真考虑。

### 条件 1：子阶段本身是长期存在的自治子流程

例如它不是一个“后台执行一次就结束”的 worker，而是一个：

- 可长期挂起
- 可长期恢复
- 可多次互动

的独立子流程实体。

### 条件 2：用户必须直接和该子阶段来回交互很多次

而且这些交互：

- 很难由主 Agent 转述
- 很难抽象成结构化输入请求
- 强烈依赖子阶段的局部上下文

### 条件 3：你愿意为此付出完整的状态机和消息路由代价

你至少要引入：

- interaction id
- waiting state
- suspended frame
- reply routing
- timeout policy
- resume policy
- multi-subagent concurrency policy

如果这套基础设施你不准备做，那么“完全独立 HITL”大概率得不偿失。

---

## 11. 对你当前 CAE 目标的具体建议

结合你说的情况，我建议分 3 个阶段推进。

---

## 12. 第一阶段：不要做 subagent 独立 HITL

这一阶段的目标是：

- 跑通 CAE 主流程
- 把技能拆分干净
- 把参数、阶段、产物理清楚

建议做法：

1. 建立 `CAEIntentClassifier`
2. 建立 `CAESkillSelector`
3. 建立 `CAESlotFillingManager`
4. 建立 `CAEPlanner`
5. 用主 Agent 做所有用户追问
6. 让 subagent 只做执行，必要时返回 `needs_user_input` / `needs_approval`

这一步通常已经足以支撑一个可靠的 CAE PoC。

---

## 13. 第二阶段：做“代理式 HITL”

也就是：

- Subagent 不直接问用户
- 但能发起结构化 HITL 请求

这一步建议新增：

- `SubagentResult`
- `UserInputRequest`
- `ApprovalRequest`
- `resume_subagent(...)`

这会让你的系统从“能问”升级为“能受控地问和恢复”。

这一步我认为是最适合 CAE 的正式工程化路线。

---

## 14. 第三阶段：只有必要时再考虑 subagent 独立 HITL

当且仅当你发现下面问题长期存在时，再考虑：

- 主 Agent 转述交互成本过高
- 某些阶段必须自己持续和用户细粒度对话
- 结构化 `needs_user_input` 已经不够表达
- 用户确实愿意接受“多主体对话”产品形态

否则不建议提前做。

---

## 15. 我对“是否需要”的最终判断

针对你当前的项目阶段和描述，我的判断是：

### 现在不需要

你现在**不需要**给 subagent 做“完全独立 HITL”。

### 现在需要的是

你现在更需要的是：

- 明确的 CAE 参数治理
- 明确的阶段规划
- 明确的 subagent 结构化返回协议
- 主 Agent 统一处理用户交互

### 未来可能需要

如果你后续把系统做成真正的多专家长生命周期代理网络，才可能需要让 subagent 自己具备完整 HITL。

但那已经不是“给现有 subagent 稍微加个功能”，而是：

**重新定义 subagent 的角色和运行模型。**

---

## 16. 一句话总结

基于当前 `nanobot` 架构和你要做的 CAE Agent，我的建议是：

**不要直接做 subagent 完全独立 HITL。**

更合适的路线是：

**让主 Agent 保持唯一用户交互入口，让 subagent 通过结构化方式请求人类介入。**

对你的场景来说，真正关键的不是“子 Agent 自己会不会说话”，而是：

**系统能不能把 CAE 的缺参、确认、恢复，做成可控、可追踪、可恢复的工程流程。**
