# CAE 外层请求过滤模块设计说明

本文档面向当前 `nanobot` 代码结构，说明是否应该为 CAE 系统增加一个“最外层请求过滤模块”，以及推荐如何实现。

适用目标：

- 这个 agent 系统只允许处理 **CAE 相关问答、脚本生成、流程执行、功能测试**
- 对于 **政治、敏感、无关领域** 请求，统一拒答
- 拒答时返回 **固定模板**
- 判断过程允许使用 **LLM 分类**
- 对于正常请求，继续走当前既有逻辑

---

## 1. 结论

结论很明确：

**应该加，而且应该加在最外层。**

原因不是“体验优化”，而是“系统边界控制”。

你现在这套系统已经具备：

- skill 发现与加载
- 多轮 HITL
- 子 agent 编排
- 文件读写
- shell 执行
- WebUI / websocket 接入

如果没有一个最外层过滤器，模型即使主提示词写着“这是 CAE 系统”，仍然可能：

- 回答与 CAE 无关的问题
- 接收并执行偏离 CAE 的脚本生成请求
- 被诱导回答政治、敏感内容
- 在复杂多轮对话中逐步偏离领域边界

所以这个模块的核心价值不是“让回复更礼貌”，而是：

1. **建立系统边界**
2. **减少 prompt 漂移**
3. **阻止非 CAE 请求进入后续 skill / tool / workflow**
4. **降低高风险输出**

---

## 2. 为什么不能只靠总 prompt

只靠 system prompt 约束“你是 CAE 系统”是不够的。

原因有四个：

### 2.1 prompt 约束不是硬门禁

LLM 看到 system prompt 后，仍然可能在以下情况下偏离：

- 用户连续多轮诱导
- 混合请求里掺入无关任务
- skill 内容很多，领域边界被稀释
- HITL 恢复时只看到局部上下文

### 2.2 当前系统允许大量工具动作

你当前 agent 不是一个纯问答机器人，而是带工具执行链路：

- `read_file`
- `write_file`
- `exec`
- `spawn`
- skill 编排

如果无关请求进入主流程，不只是“回答错了”，还可能继续：

- 生成无关脚本
- 调起子 skill
- 读写不该读写的业务文件

### 2.3 WebUI 会放大真实使用风险

WebUI 上用户使用更随意，输入比 CLI 更像自然对话。

如果没有最外层过滤：

- 用户更容易直接问无关问题
- 也更容易把系统误当通用助手

### 2.4 你要的目标是“领域型系统”，不是“通用 LLM”

你现在已经明确：

- 这是 CAE 系统
- 只允许 CAE 相关
- 敏感/政治直接拒绝

那就不应把这个边界只放在 prompt 里，而应该落实为一个 **显式模块**。

---

## 3. 这个模块应不应该只用 LLM

我的建议是：

**不要做成“纯 LLM 分类器”，而要做成“规则 + LLM”的两段式过滤”。**

原因如下。

### 3.1 纯 LLM 分类的优点

- 语义理解强
- 能处理中文自然表达
- 能识别隐式 CAE 请求
- 能识别“这是 workflow 的补充输入，而不是完整问题”

### 3.2 纯 LLM 分类的缺点

- 成本更高
- 多一次模型调用
- 结果有波动
- 极短输入容易误判
  - 例如 `steel`
  - 例如 `mesh_size: 2.0 mm`
  - 例如 `继续`

这些短输入在 HITL 恢复里是合法的，但单看文本很不像“CAE 请求”。

### 3.3 推荐方案

推荐做成 3 层：

1. **命令/系统消息白名单 bypass**
2. **轻量规则预筛**
3. **LLM 语义判定**

这样能兼顾：

- 稳定性
- 性能
- 可解释性
- 命中率

---

## 4. 推荐的过滤策略

推荐将请求分成 4 类：

### 类别 A：允许

满足以下任一条件：

- 明确是 CAE 相关问答
- 明确是 CAE 脚本生成
- 明确是 CAE 流程执行
- 明确是当前 workflow 的 HITL 回复
- 明确是某个 CAE skill 的调用

处理方式：

- 直接进入当前主流程

### 类别 B：拒绝

满足以下任一条件：

- 政治类
- 敏感类
- 与 CAE 无关的通用闲聊
- 与 CAE 无关的代码生成
- 与 CAE 无关的工具执行请求

处理方式：

- 直接返回固定模板
- 不再进入 skill / tool / workflow

### 类别 C：不确定

例如：

- 文本极短
- 缩写很多
- 只给一个参数名
- 既像 CAE，又像别的领域

处理方式：

- 交给 LLM 分类器做二次语义判断

### 类别 D：系统内部消息

例如：

- `channel == "system"`
- subagent outcome
- 内部 follow-up

处理方式：

- 不做领域过滤
- 直接走现有流程

---

## 5. 固定拒答模板

你说“直接回答一个固定模板就可以”，这很好，建议不要给太多解释。

推荐统一模板：

```text
抱歉，我只能处理 CAE 相关的问答、脚本生成和流程执行请求。当前请求不在允许范围内，因此不能继续处理。
```

如果你希望更强硬一点，也可以用：

```text
抱歉，该请求不属于允许的 CAE 范围，我不能回答或执行。
```

建议：

- **全系统只保留一个模板**
- 不要按政治/敏感/无关再细分模板
- 不要暴露分类规则细节
- 不要让模型自由发挥拒答文案

这样有三个好处：

1. 行为稳定
2. 前端体验一致
3. 方便测试与日志统计

---

## 6. 最适合的接入位置

结合当前代码，最合适的接入位置是：

- 文件：`D:\code\nanobot\nanobot\nanobot\agent\loop.py`
- 方法：`AgentLoop._process_message(...)`

当前关键入口位置：

- `run()` 在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:565](D:/code/nanobot/nanobot/nanobot/agent/loop.py:565)
- `_dispatch()` 在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:640](D:/code/nanobot/nanobot/nanobot/agent/loop.py:640)
- `_process_message()` 在 [D:\code\nanobot\nanobot\nanobot\agent\loop.py:774](D:/code/nanobot/nanobot/nanobot/agent/loop.py:774)

### 为什么应该接在 `_process_message()` 而不是更前面

因为这里已经具备了：

- `msg.channel`
- `msg.content`
- `session`
- 当前 workflow 状态
- slash command 分发逻辑
- system/subagent 区分

也就是说，在这个位置做过滤最容易做到：

- 不误伤 `/new`、`/stop`
- 不误伤 system/subagent 消息
- 能识别当前是不是 HITL 恢复
- 能统一覆盖 CLI / WebUI / websocket

### 推荐插入点

推荐插在：

1. slash command 之后
2. workflow 恢复逻辑之前

更具体地说，在这段附近：

```python
raw = msg.content.strip()
ctx = CommandContext(...)
if result := await self.commands.dispatch(ctx):
    return result
```

之后，加：

```python
filter_result = await self._apply_cae_request_filter(session, msg)
if filter_result is not None:
    return filter_result
```

然后再进入：

- active workflow 检查
- `_resume_blocked_workflow(...)`
- context build
- LLM 主循环

---

## 7. 为什么不是接在 channel 层

也可以把过滤放在 websocket / cli channel 层，但我不建议。

原因：

### 7.1 channel 层拿不到 workflow 语义

channel 层通常只知道：

- 收到一条消息

但不知道：

- 当前 session 有没有 active workflow
- 这条输入是不是 HITL 回复
- 当前是不是 resume 阶段

### 7.2 channel 层会导致多处重复

你现在已经支持：

- CLI
- WebSocket / WebUI
- 后续可能还有别的 channel

如果过滤逻辑分散在 channel 层，就要：

- 每个入口都接一次

这不利于统一维护。

### 7.3 AgentLoop 才是统一业务入口

当前 `AgentLoop` 已经是你系统的统一编排中心，所以领域过滤也应该放在这里。

---

## 8. 推荐的新模块结构

建议新增一个独立模块，而不是把所有逻辑都塞进 `loop.py`。

推荐结构：

```text
nanobot/
  agent/
    guardrails/
      __init__.py
      cae_filter.py
      models.py
      prompts.py
```

### 8.1 `cae_filter.py`

负责：

- 外层过滤主逻辑
- 规则预筛
- LLM 分类调用
- 输出统一结果

### 8.2 `models.py`

负责定义结构化结果，例如：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class CAEFilterDecision:
    action: Literal["allow", "deny"]
    reason: str
    classifier: Literal["rule", "llm", "bypass"]
```

### 8.3 `prompts.py`

负责存放分类 prompt，避免写死在 `loop.py`。

---

## 9. 推荐的配置项

建议在配置里新增一个 guardrail 配置段。

当前配置文件在：

- [D:\code\nanobot\nanobot\nanobot\config\schema.py](D:/code/nanobot/nanobot/nanobot/config/schema.py)

建议新增：

```python
class CAEGuardrailConfig(Base):
    enable: bool = True
    mode: Literal["rule_only", "rule_plus_llm", "llm_only"] = "rule_plus_llm"
    deny_template: str = "抱歉，我只能处理 CAE 相关的问答、脚本生成和流程执行请求。当前请求不在允许范围内，因此不能继续处理。"
    classifier_model: str | None = None
    allow_system_messages: bool = True
    allow_commands: bool = True
```

然后放到：

```python
class AgentDefaults(Base):
    ...
    cae_guardrail: CAEGuardrailConfig = Field(default_factory=CAEGuardrailConfig)
```

### 当前实现状态

当前代码已经按这个结构实现，并且为了不影响通用场景，**默认是关闭的**：

```json
{
  "agents": {
    "defaults": {
      "caeGuardrail": {
        "enable": false
      }
    }
  }
}
```

如果你要在 CAE 部署里启用它，建议在 `config.json` 中显式打开：

```json
{
  "agents": {
    "defaults": {
      "caeGuardrail": {
        "enable": true,
        "mode": "rule_plus_llm",
        "denyTemplate": "抱歉，我只能处理 CAE 相关的问答、脚本生成和流程执行请求。当前请求不在允许范围内，因此不能继续处理。"
      }
    }
  }
}
```

### 配置含义

- `enable`
  - 总开关
- `mode`
  - 规则 only
  - 规则 + LLM
  - LLM only
- `deny_template`
  - 固定拒答模板
- `classifier_model`
  - 可选单独指定一个更便宜的小模型做分类
- `allow_system_messages`
  - system/subagent outcome 是否跳过过滤
- `allow_commands`
  - `/new` `/stop` 等命令是否跳过过滤

---

## 10. 推荐的判定逻辑

### 10.1 总体流程

推荐流程如下：

```text
用户消息
  ->
命令/系统消息 bypass
  ->
规则预筛
  ->
如果已明确允许/拒绝，直接返回
  ->
否则调用 LLM 分类器
  ->
allow / deny
```

### 10.2 bypass 规则

以下情况直接跳过过滤：

1. `msg.channel == "system"`
2. slash command
3. agent 内部 follow-up
4. subagent outcome

### 10.3 规则预筛：允许

以下情况可直接允许，不必进 LLM 分类：

- 用户明确提到了 CAE 关键词
  - `cae`
  - `cad`
  - `mesh`
  - `网格`
  - `物理场`
  - `前处理`
  - `后处理`
  - `应力`
  - `位移`
  - `边界条件`
  - `求解`
- 用户明确提到 CAE skill
- 当前 session 有 active workflow，且消息形态像 HITL 参数回复
  - `xxx: yyy`
  - 多个 `name: value`

### 10.4 规则预筛：拒绝

以下情况可直接拒绝，不必进 LLM 分类：

- 明显政治人物 / 政治事件 / 选举 / 政策评价
- 明显色情、暴力、违法
- 明显通用闲聊
  - “你是谁”
  - “帮我写情书”
  - “推荐电影”
- 明显无关领域代码请求
  - “帮我写一个电商网站”
  - “写一个股票量化策略”

### 10.5 LLM 分类器只处理灰区

只有当规则无法确定时，才交给 LLM。

这能显著减少：

- 成本
- 时延
- 误判

---

## 11. LLM 分类器 prompt 设计

建议 LLM 分类器只输出结构化 JSON，不输出解释性长文本。

### 推荐输入

分类器输入应包含：

- 当前用户消息
- 是否存在 active workflow
- 当前 stage（如果有）
- 当前是否处于 HITL 恢复

### 推荐输出

```json
{
  "action": "allow",
  "category": "cae_workflow_reply",
  "confidence": 0.94
}
```

或：

```json
{
  "action": "deny",
  "category": "political_or_out_of_scope",
  "confidence": 0.98
}
```

### 推荐 prompt

```text
你是一个 CAE 系统的请求分类器。

你的任务不是回答用户，而是判断这条消息是否允许进入 CAE agent 主流程。

允许的范围只有：
1. CAE 相关问答
2. CAE 相关脚本生成
3. CAE 相关流程执行
4. 当前 workflow 的 HITL 参数回复

必须拒绝的范围包括：
1. 政治
2. 敏感公共议题
3. 与 CAE 无关的通用问答
4. 与 CAE 无关的代码、工具、执行请求

你必须只输出 JSON，不要输出任何解释。
```

### 一个关键点

分类器要知道：

- **短参数输入在 HITL 中是合法的**

例如：

```text
mesh_size: 2.0 mm
group2_value: beta
steel
```

这些在通用文本里可能很模糊，但在 active workflow 中应判为允许。

---

## 12. 关键实现细节

### 12.1 过滤结果不应写入正常 assistant history

如果命中拒绝模板：

- 可以记录一条 assistant 消息
- 但不要再继续进入 skill / tool / main LLM loop

建议直接返回：

```python
return OutboundMessage(
    channel=msg.channel,
    chat_id=msg.chat_id,
    content=deny_template,
)
```

### 12.2 过滤器不能破坏 HITL 恢复

这是最关键的风险点。

如果当前 workflow 正处于：

- `awaiting_user_input`
- `awaiting_approval`
- `resuming`

那么过滤器必须知道：

- 这条消息可能只是参数回复

否则会把：

```text
mesh_size: 2.0 mm
```

误判为“不是 CAE 请求”。

所以分类器入参里必须包含：

- `workflow_state`
- `workflow_stage`
- `active_workflow_id`

### 12.3 不要过滤 system 消息

subagent 的回调消息、follow-up、tool 结果，不应该再做 CAE 领域过滤。

否则会导致：

- 正常子流程结果被挡掉

### 12.4 不要过滤 slash command

像：

- `/new`
- `/stop`

这些应始终允许。

---

## 13. 推荐实现步骤

建议按下面顺序做，而不是一次性大改。

### 第一步：先加文档与配置结构

先落：

- `CAEGuardrailConfig`
- 拒答模板
- 文档

目标：

- 把行为边界先固定下来

### 第二步：先做 `rule_only`

先只做：

- bypass
- 允许关键词
- 拒绝关键词

目标：

- 快速验证接入点是否正确
- 验证不会破坏 workflow / HITL

### 第三步：再加 `rule_plus_llm`

对灰区请求增加 LLM 分类。

目标：

- 提升中文语义判断能力
- 降低关键词误杀

### 第四步：补日志与测试

增加日志：

```text
[CAE_FILTER] allow via rule
[CAE_FILTER] deny via llm
[CAE_FILTER] bypass due to system message
```

这样后续在 WebUI 测试时，很容易看出：

- 请求为什么被挡
- 是规则挡的还是 LLM 挡的

---

## 14. 推荐代码接入形态

在 `AgentLoop` 里建议新增一个辅助方法：

```python
async def _apply_cae_request_filter(
    self,
    session: Session,
    msg: InboundMessage,
) -> OutboundMessage | None:
    ...
```

返回约定：

- 返回 `None`：允许继续主流程
- 返回 `OutboundMessage`：表示已拒绝并终止当前请求

内部再调用一个独立类，例如：

```python
decision = await self.cae_filter.evaluate(
    text=msg.content,
    workflow=workflow,
    channel=msg.channel,
)
```

---

## 15. 推荐测试用例

### 15.1 应允许

```text
请运行一个悬臂梁 CAE 流程
```

```text
project_name: cantilever-demo
```

```text
mesh_size: 2.0 mm
```

```text
我已经完成 cad 和网格，请继续物理场
```

### 15.2 应拒绝

```text
请评价某个政治人物
```

```text
请帮我分析国际政治局势
```

```text
帮我写一个电商后台
```

```text
推荐几部最近的电影
```

### 15.3 灰区，应走 LLM

```text
我想继续上一阶段
```

```text
steel
```

```text
继续
```

如果当前有 active workflow，这些应判为允许。  
如果没有 active workflow，这些更可能应被拒绝或继续澄清。

---

## 16. 风险与注意事项

### 16.1 “敏感”定义不能太泛

如果“敏感”定义过宽，会误杀正常工程请求。

例如：

- “材料属性”
- “失效模式”
- “极限载荷”

这些在 CAE 里完全正常。

所以建议把“拒绝类”先收窄为：

- 政治
- 明显无关领域
- 明显违规内容

### 16.2 不要把分类器做成主模型的一部分提示词

过滤器最好是独立模块、独立决策。

否则：

- 过滤和主回答混在一起
- 难测试
- 难打日志
- 难稳定

### 16.3 不要让拒绝模板进入子 skill

过滤器一定要在 skill 调度前挡住请求。

否则会出现：

- skill 已经被命中
- subagent 已经被启动
- 最后才拒绝

这就太晚了。

---

## 17. 最终建议

如果你现在要落地，我的推荐是：

1. **一定要加**
2. **放在 `AgentLoop._process_message()` 的最外层主用户消息入口**
3. **采用“规则 + LLM”两段式**
4. **system/subagent/slash command 全部 bypass**
5. **统一固定拒答模板**
6. **过滤器单独成模块，不要塞进 skill**

---

## 18. 一句话版本

这不是一个“可选增强”，而是一个 **CAE 领域系统的边界控制模块**。  
最合理的做法是在 `AgentLoop` 的主用户消息入口增加一个独立 guardrail：先用规则快速筛，再用 LLM 判断灰区，命中拒绝后直接返回固定模板，允许则继续走现有 CAE workflow 逻辑。
