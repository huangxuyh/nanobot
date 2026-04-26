# nanobot 改造为 CAE Agent 的二次开发报告

## 1. 报告目标

本文档面向 `nanobot` 项目的二次开发，目标是将当前通用 Agent 框架改造为一个面向 CAE 领域的 Agent。

用户期望的核心能力包括：

1. 支持多级意图分类。
2. 区分闲聊与 CAE 操作。
3. 对 CAE 操作进行细粒度分类，例如几何、网格、物理场、耦合、优化、寿命评估、疲劳、后处理等。
4. 支持 CAE 操作函数注册，并基于用户意图调用单个函数或组合多个函数。
5. 支持函数参数识别、参数校验和多轮确认。
6. 当自然语言输入缺少必要参数时，能够主动向用户追问。
7. 最终 CAE 操作输出为 Python 脚本。
8. 通过已注册的仿真软件执行接口执行该 Python 脚本。

本文会明确指出：

- 当前 `nanobot` 已经具备哪些能力。
- 哪些能力只需要通过提示词、技能或组件编排即可实现。
- 哪些能力当前不存在，需要新增模块开发。
- 推荐的总体架构、模块划分、数据结构、流程和开发路线。

---

## 2. 总体结论

`nanobot` 适合作为 CAE Agent 的基础运行时，但需要在其上新增一层 CAE 专用业务编排层。

当前项目已经具备以下可直接复用能力：

| 目标能力 | 当前项目是否已有 | 说明 |
|---|---:|---|
| LLM 多轮 Agent 运行循环 | 已有 | `AgentRunner` 和 `AgentLoop` 已经支持工具调用循环 |
| Function call / Tool call | 已有 | 通过 `Tool`、`ToolRegistry`、JSON Schema 参数定义实现 |
| 文件读写 | 已有 | `read_file`、`write_file`、`edit_file`、`list_dir` |
| Shell 执行 | 已有 | `exec` 工具可执行外部命令 |
| MCP 工具接入 | 已有 | 可把外部工具服务注册为 Agent 工具 |
| Skill 能力 | 已有 | `SkillsLoader` 已支持 workspace skills 和 builtin skills，适合沉淀成熟 CAE 操作流程 |
| 多轮对话上下文 | 已有 | `SessionManager` 已保存对话历史 |
| 长任务/后台任务 | 部分已有 | `Subagent`、`cron`、`heartbeat` 可复用，但不是工业级作业系统 |
| OpenAI-compatible API | 已有 | 可作为前端或系统集成入口 |
| Python SDK | 已有 | 可作为程序内调用入口 |

当前项目缺少或不足的能力：

| 目标能力 | 当前项目状态 | 建议 |
|---|---|---|
| 显式意图分类模块 | 缺少 | 新增 `CAEIntentClassifier` |
| 多级 CAE 任务分类体系 | 缺少 | 新增 CAE taxonomy 和分类 schema |
| CAE 操作注册中心 | 缺少专用实现 | 新增 `CAEFunctionRegistry`，短期也可直接注册为 `Tool` |
| 参数槽位补全 | 缺少显式状态机 | 新增 `CAESlotFillingManager` |
| 多轮参数确认状态保存 | 缺少 CAE 专用状态 | 可扩展 `session.metadata` 或新增 CAE task store |
| 函数编排计划 | 缺少 | 新增 `CAEPlanner` |
| CAE Skill 选择与执行策略 | 部分已有 | 当前可加载 skill，但缺少面向 CAE taxonomy 的显式 skill 匹配、优先级和执行状态 |
| Python 脚本组合与校验 | 缺少 | 新增 `CAEScriptBuilder` 和 `CAEScriptValidator` |
| 仿真软件执行接口 | 缺少领域接口 | 新增 `CAESimulatorExecutorTool` |
| 结构化结果后处理 | 缺少 | 新增后处理工具与结果 schema |

推荐总体策略：

> 短期采用低侵入方式，把 CAE 操作函数注册成 `nanobot Tool`，用提示词约束 Agent 进行分类、追问和函数调用；中长期新增显式 CAE Router、Intent Classifier、Slot Filling、Planner、Script Builder 和 Executor，使系统从“LLM 自主工具调用”升级为“受控工程流程编排”。

---

## 3. 当前项目能力复用分析

### 3.1 Function call 能力已经具备

`nanobot` 的工具系统已经等价于 function call 系统。

核心代码位置：

- `nanobot/agent/tools/base.py`
- `nanobot/agent/tools/registry.py`
- `nanobot/agent/runner.py`
- `nanobot/agent/loop.py`

当前每个工具都继承 `Tool`，并提供：

- `name`
- `description`
- `parameters`
- `execute(**kwargs)`

`parameters` 使用 JSON Schema 描述，所以可以表达函数参数类型、必填项、枚举、数组、对象等。

这意味着你要注册一个 CAE 函数时，可以直接实现为：

```python
class CreateGeometryTool(Tool):
    @property
    def name(self) -> str:
        return "cae_create_geometry"

    @property
    def description(self) -> str:
        return "Generate a CAE geometry Python script fragment from structured geometry parameters."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "geometry_type": {"type": "string", "enum": ["beam", "plate", "bracket", "custom"]},
                "dimensions": {"type": "object"},
                "unit": {"type": "string", "enum": ["mm", "m"]},
            },
            "required": ["geometry_type", "dimensions", "unit"],
        }

    async def execute(self, **kwargs):
        ...
```

然后在工具注册阶段加入 `ToolRegistry` 即可。

### 3.2 MCP 可作为 CAE 工具接入方式

如果你的 CAE 操作函数已经存在于独立服务中，或者希望未来与多个系统共享，优先建议用 MCP 接入。

适合 MCP 化的能力包括：

- 几何建模服务
- 网格生成服务
- 求解器作业提交服务
- 后处理服务
- 材料数据库查询
- 历史算例检索
- 优化算法服务

当前项目已经支持把 MCP tools / resources / prompts 自动注册为 Agent 工具。因此，如果你能把 CAE 操作包装成 MCP server，`nanobot` 侧只需要配置 `mcpServers` 即可接入。

### 3.3 Skill 能力已经具备，适合沉淀成熟 CAE 操作流程

当前项目已经支持 Skill 功能。

核心代码位置：

- `nanobot/agent/skills.py`
- `nanobot/agent/context.py`
- `nanobot/skills/`
- `workspace/skills/`

`SkillsLoader` 会加载两类 skill：

- 项目内置 skill：`nanobot/skills/<skill_name>/SKILL.md`
- 工作区 skill：`workspace/skills/<skill_name>/SKILL.md`

工作区 skill 优先级高于内置 skill。同名情况下，工作区 skill 可以覆盖内置 skill。这对 CAE 二次开发很有价值，因为你可以把通用、成熟、可复用的 CAE 操作流程沉淀为 skill，而不是每次都依赖 LLM 临时规划。

适合做成 CAE skill 的内容包括：

- 标准静力分析流程。
- 标准模态分析流程。
- 标准热分析流程。
- 网格划分质量检查流程。
- 疲劳分析前处理流程。
- 后处理报告生成规范。
- 特定仿真软件的 Python API 使用规范。
- 企业内部建模规范、命名规范、单位规范。

不建议只用 skill 承载的内容包括：

- 真正执行仿真软件的接口。
- 需要强参数校验的核心操作。
- 需要访问数据库或许可证系统的操作。
- 长时间运行的求解作业。

这些应实现为 Tool、MCP tool 或 CAE executor，由 skill 负责编排和说明使用方式。

因此，推荐把 skill 定位为：

> **CAE 流程知识和操作规范层，而不是底层执行层。**

### 3.4 多轮对话能力已有，但参数补全需要增强

当前项目有会话历史保存，所以从 LLM 角度可以进行多轮追问。但如果只靠提示词实现参数收集，存在几个问题：

- 参数是否完整不可控。
- 用户补充信息是否正确写入对应参数不可控。
- 多个函数组合时，参数依赖关系容易混乱。
- 很难做工程审计。

因此，简单 PoC 可以先靠提示词和工具 schema 让 Agent 自己追问；但正式 CAE Agent 建议新增显式 Slot Filling 状态机。

### 3.5 Python 脚本输出可以复用文件工具，但建议新增脚本构建器

当前 `write_file` 已能写 Python 文件，`exec` 已能执行命令。因此最简单链路是：

1. Agent 生成 Python 脚本。
2. `write_file` 写入 `.py`。
3. `exec` 调用仿真软件执行。

但这种方式不够安全，也不够可控。推荐新增：

- `cae_build_script`
- `cae_validate_script`
- `cae_run_simulation`

让脚本生成、静态校验和执行分离。

---

## 4. 推荐目标架构

### 4.1 总体架构

建议在 `nanobot` 现有 Agent 运行时上新增 `nanobot/cae/` 模块。

```text
用户输入
  |
  v
CAEIntentRouter
  |
  +-- 闲聊/普通问答 -> 原 nanobot AgentLoop
  |
  +-- CAE 操作
        |
        v
  CAEIntentClassifier
        |
        v
  CAESkillSelector
        |
        +-- 命中成熟 skill -> 按 skill 指导选择函数/参数/流程
        |
        v
  CAEFunctionRegistry
        |
        v
  CAESlotFillingManager
        |
        +-- 参数不足 -> 生成追问 -> 用户补充 -> 回到 Slot Filling
        |
        +-- 参数完整
              |
              v
        CAEPlanner
              |
              v
        CAEScriptBuilder
              |
              v
        CAEScriptValidator
              |
              v
        CAESimulatorExecutorTool
              |
              v
        CAEPostProcessor
              |
              v
        返回结果/报告
```

### 4.2 推荐新增目录结构

```text
nanobot/
  cae/
    __init__.py
    taxonomy.py
    schemas.py
    intent.py
    router.py
    skill_selector.py
    registry.py
    slot_filling.py
    planner.py
    script_builder.py
    script_validator.py
    executor.py
    postprocess.py
    tools.py
    prompts/
      intent_classifier.md
      skill_selection.md
      slot_filling.md
      planner.md
      script_generation.md
      result_interpretation.md
```

### 4.3 与现有项目的集成点

推荐优先修改或扩展以下位置：

| 文件 | 改造点 |
|---|---|
| `nanobot/agent/loop.py` | 在 `_process_message()` 早期加入 CAE Router |
| `nanobot/agent/tools/registry.py` | 可保持不变，注册 CAE Tool 即可 |
| `nanobot/config/schema.py` | 增加 `CaeConfig` |
| `nanobot/nanobot.py` | SDK 可增加 CAE 专用参数或保持兼容 |
| `nanobot/templates/` 或 `nanobot/cae/prompts/` | 增加 CAE 专用提示词 |
| `docs/` | 增加 CAE 操作函数注册规范 |

---

## 5. 意图分类模块设计

### 5.1 当前项目是否已支持

当前项目没有显式意图分类模块。

但当前项目已经可以通过系统提示词让 LLM 自行判断：

- 用户是不是闲聊。
- 是否需要调用工具。
- 应该调用哪个工具。
- 如果参数不足则追问。

这种方式可用于 PoC，但不建议用于正式 CAE Agent。原因是 CAE 操作风险较高，需要稳定、可追踪、可验证的分类和参数状态。

### 5.2 推荐新增 CAEIntentClassifier

建议新增一个独立分类模块，输出结构化分类结果。

示例数据结构：

```python
from pydantic import BaseModel, Field
from typing import Literal

class CAEIntentResult(BaseModel):
    top_level: Literal["chat", "cae", "project_management", "unknown"]
    cae_domain: str | None = None
    cae_task: str | None = None
    cae_subtask: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    requires_tools: bool = False
    suggested_operations: list[str] = []
    extracted_entities: dict = {}
    missing_information_hint: list[str] = []
    user_goal_summary: str = ""
```

### 5.3 多级分类体系

建议采用三级或四级意图分类。

一级分类：

| 一级分类 | 说明 |
|---|---|
| `chat` | 闲聊、解释、概念问答、不需要执行 CAE 操作 |
| `cae` | 需要创建、修改、执行或分析 CAE 流程 |
| `project_management` | 算例管理、文件管理、任务状态查询 |
| `unknown` | 意图不明确 |

二级 CAE 分类：

| 二级分类 | 说明 |
|---|---|
| `geometry` | 几何建模、几何导入、几何清理、参数化几何 |
| `mesh` | 网格划分、网格质量检查、局部加密 |
| `physics` | 材料、边界条件、载荷、物理场设置 |
| `coupling` | 多物理场耦合、流固耦合、热结构耦合 |
| `optimization` | 参数优化、拓扑优化、形状优化 |
| `life_assessment` | 寿命评估、可靠性、耐久性 |
| `fatigue` | 疲劳载荷、S-N 曲线、疲劳损伤 |
| `postprocessing` | 结果提取、云图、曲线、报告生成 |
| `workflow` | 完整仿真流程编排 |
| `execution` | 求解器执行、状态查询、日志分析 |

三级任务示例：

| 二级分类 | 三级任务 |
|---|---|
| `geometry` | `create_geometry`、`import_cad`、`clean_geometry`、`parameterize_geometry` |
| `mesh` | `generate_mesh`、`check_mesh_quality`、`refine_mesh` |
| `physics` | `assign_material`、`apply_boundary_condition`、`apply_load`、`define_contact` |
| `coupling` | `setup_thermal_structural`、`setup_fsi`、`map_fields` |
| `optimization` | `define_design_variables`、`define_objective`、`run_optimization` |
| `life_assessment` | `setup_life_model`、`evaluate_life` |
| `fatigue` | `define_fatigue_load`、`calculate_damage`、`evaluate_safety_factor` |
| `postprocessing` | `extract_result`、`plot_contour`、`generate_report` |
| `workflow` | `run_static_analysis`、`run_modal_analysis`、`run_thermal_analysis`、`run_full_pipeline` |

四级可用于具体软件或求解器动作：

- `abaqus.create_part`
- `ansys.apply_pressure`
- `comsol.setup_multiphysics`
- `openfoam.generate_mesh`
- `custom_solver.submit_job`

### 5.4 分类实现方案

推荐三种实现方式，按阶段逐步升级。

#### 方案 A：提示词分类

这是最小改造方案。

做法：

- 新增 `CAE_INTENT_CLASSIFIER.md` 提示词。
- 让 LLM 返回严格 JSON。
- 在 `_process_message()` 前调用一次分类模型。

优点：

- 开发快。
- 不需要训练模型。
- 对新任务扩展灵活。

缺点：

- 稳定性取决于模型。
- 对分类边界缺少强约束。

#### 方案 B：规则 + LLM 混合分类

推荐作为第一版正式实现。

做法：

- 规则层先识别高置信度关键词，例如“网格”、“边界条件”、“疲劳”、“云图”、“求解”、“后处理”。
- LLM 层处理复杂表达。
- 当规则和 LLM 不一致时，进入澄清流程。

优点：

- 稳定性更高。
- 成本较低。
- 方便调试和审计。

#### 方案 C：训练轻量分类模型

适合后期已有大量真实用户数据后使用。

做法：

- 收集真实用户请求和标注。
- 训练分类模型或 embedding 检索分类器。
- LLM 只处理低置信度样本。

优点：

- 可控性最好。
- 成本最低。

缺点：

- 初期数据不足。
- 分类体系变化时需要维护数据。

---

## 6. CAE 函数注册与 Function Call 设计

### 6.1 当前项目是否已支持

当前项目已经支持函数调用，但没有 CAE 专用函数注册中心。

你现在可以直接把 CAE 操作写成 `Tool` 并注册到 `ToolRegistry` 中。这种方式能够满足最小 PoC。

但长期来看，CAE 函数需要更多元数据，仅靠普通 Tool 不够。例如：

- 属于哪个 CAE 域。
- 依赖哪些前置操作。
- 输出是脚本片段、完整脚本、结果文件还是状态。
- 是否允许直接执行。
- 支持哪些仿真软件。
- 必填参数和默认参数。
- 参数缺失时该如何追问。
- 参数单位如何处理。
- 是否需要用户确认。

因此建议新增 `CAEFunctionRegistry`。

### 6.2 CAEFunctionSpec 设计

建议定义统一函数描述：

```python
from pydantic import BaseModel
from typing import Literal

class CAEParameterSpec(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str
    unit: str | None = None
    enum: list[str] | None = None
    default: object | None = None
    ask_when_missing: str | None = None
    examples: list[str] = []

class CAEFunctionSpec(BaseModel):
    name: str
    display_name: str
    domain: str
    task: str
    description: str
    parameters: list[CAEParameterSpec]
    output_type: Literal["script_fragment", "script", "result", "job_id", "metadata"]
    supported_solvers: list[str]
    dependencies: list[str] = []
    requires_confirmation: bool = False
    safety_level: Literal["read", "write_script", "execute"] = "write_script"
```

### 6.3 函数输出建议

不要让每个 CAE 函数直接返回任意自然语言。建议统一返回结构化结果。

```python
class CAEFunctionResult(BaseModel):
    ok: bool
    function_name: str
    script_fragment: str | None = None
    data: dict = {}
    warnings: list[str] = []
    errors: list[str] = []
```

这样后续 `CAEScriptBuilder` 可以可靠拼接脚本。

### 6.4 注册方式

短期方式：

- 每个 CAE 操作实现为 `Tool`。
- 在 `AgentLoop._register_default_tools()` 中直接注册。

示例：

```python
def _register_default_tools(self) -> None:
    ...
    from nanobot.cae.tools import (
        CreateGeometryTool,
        GenerateMeshTool,
        ApplyBoundaryConditionTool,
        BuildScriptTool,
        RunSimulationTool,
    )

    self.tools.register(CreateGeometryTool())
    self.tools.register(GenerateMeshTool())
    self.tools.register(ApplyBoundaryConditionTool())
    self.tools.register(BuildScriptTool(workspace=self.workspace))
    self.tools.register(RunSimulationTool(workspace=self.workspace))
```

长期方式：

- 新增 `CAEFunctionRegistry`。
- 从 Python entry point、YAML/JSON manifest 或 MCP server 自动发现 CAE 操作。
- 自动转换为 `nanobot Tool`。

推荐 manifest 示例：

```yaml
name: cae_generate_mesh
displayName: Generate Mesh
domain: mesh
task: generate_mesh
description: Generate mesh script fragment for the selected geometry.
outputType: script_fragment
supportedSolvers:
  - custom_cae
parameters:
  - name: geometry_id
    type: string
    required: true
    description: Geometry object identifier.
    askWhenMissing: "请提供要划分网格的几何对象或几何文件路径。"
  - name: global_size
    type: number
    required: true
    unit: mm
    description: Global mesh size.
    askWhenMissing: "请提供全局网格尺寸，例如 2 mm。"
  - name: element_type
    type: string
    required: false
    enum: ["tet", "hex", "shell", "beam"]
    default: "tet"
```

### 6.5 CAE Skill 与 Function Call 的协同方式

CAE skill 和 function call 不应互相替代，而应分层协同。

推荐关系如下：

| 层级 | 职责 | 示例 |
|---|---|---|
| Skill | 描述成熟流程、判断规则、操作顺序、注意事项 | “标准静力分析流程”“网格质量检查规范” |
| Function / Tool | 执行确定性动作 | `cae_generate_mesh`、`cae_build_script` |
| Planner | 把 skill 中的流程规范转为可执行函数链 | `import_geometry -> mesh -> load -> solve` |
| Slot Filling | 根据函数参数和 skill 规则追问缺失信息 | 缺少材料、载荷、网格尺寸时追问 |
| Executor | 执行最终 Python 脚本或求解作业 | `cae_run_simulation` |

推荐执行逻辑：

1. `CAEIntentClassifier` 判断用户是否为 CAE 操作。
2. `CAESkillSelector` 根据分类结果和用户目标查找可用 CAE skill。
3. 如果命中高置信度 skill，则把该 skill 作为 planner 的流程约束。
4. `CAEPlanner` 根据 skill 描述选择函数链。
5. `CAESlotFillingManager` 根据函数 schema 和 skill 规则收集参数。
6. 参数完整后执行函数链，生成 Python 脚本。

示例：

用户输入：

> 帮我对支架做一个标准静力分析。

系统处理：

```text
1. 分类：cae.workflow.run_static_analysis
2. skill 命中：standard_static_analysis
3. skill 规定流程：
   - 导入几何
   - 指定材料
   - 生成网格
   - 设置静力步
   - 施加约束和载荷
   - 求解
   - 提取最大应力和最大位移
4. Planner 将流程映射为 CAE 函数链
5. Slot Filling 追问缺失参数
6. Script Builder 输出 Python 脚本
```

这样做的好处是：

- 通用成熟流程不需要每次重新规划。
- CAE 专家经验可以沉淀为文档化 skill。
- 函数调用仍然保持结构化和可校验。
- 复杂流程可以由 skill 约束，避免 LLM 自由发挥。

---

## 7. 参数补全与多轮确认设计

### 7.1 当前项目是否已支持

当前项目能支持多轮对话，但没有显式参数槽位管理。

如果只靠提示词，Agent 可以问：

> 请补充材料、载荷、边界条件和网格尺寸。

但系统无法稳定知道：

- 哪些参数已经填完。
- 哪些参数仍然缺失。
- 用户的新回答对应哪个槽位。
- 参数是否通过单位和类型校验。
- 是否可以进入脚本生成阶段。

因此建议新增 `CAESlotFillingManager`。

### 7.2 Slot Filling 状态结构

建议在 `session.metadata` 中保存待完成的 CAE 任务状态。

```python
class CAETaskState(BaseModel):
    task_id: str
    status: Literal["collecting_params", "ready", "script_built", "executing", "completed", "failed"]
    intent: CAEIntentResult
    selected_skill: str | None = None
    selected_functions: list[str]
    slots: dict[str, object]
    missing_slots: list[str]
    slot_questions: dict[str, str]
    confirmations: dict[str, bool] = {}
    script_path: str | None = None
    job_id: str | None = None
```

存储位置建议：

- PoC：直接存在 `session.metadata["cae_pending_task"]`。
- 正式版：新增 `workspace/cae/tasks/<task_id>.json`，session 只保存 `task_id`。

### 7.3 参数提取流程

用户首次输入：

> 帮我对这个支架做一个静力分析。

系统分类结果：

```json
{
  "top_level": "cae",
  "cae_domain": "workflow",
  "cae_task": "run_static_analysis",
  "confidence": 0.86,
  "requires_tools": true,
  "suggested_operations": [
    "cae_import_geometry",
    "cae_assign_material",
    "cae_generate_mesh",
    "cae_apply_boundary_condition",
    "cae_apply_load",
    "cae_create_static_step",
    "cae_build_script",
    "cae_run_simulation"
  ]
}
```

Slot Filling 发现缺失参数：

- 几何文件或几何来源
- 材料
- 约束位置
- 载荷类型和大小
- 网格尺寸
- 求解器类型

系统不应直接执行，而应追问：

```text
要生成静力分析脚本，还需要确认以下信息：

1. 几何文件路径或几何对象是什么？
2. 材料参数是什么？例如弹性模量、泊松比、密度，或直接给材料名称。
3. 约束施加在哪个面/边/点？
4. 载荷类型、大小和方向是什么？
5. 期望的网格尺寸是多少？
6. 使用哪个仿真软件执行？
```

用户补充后，Slot Filling 再进行参数抽取和校验。

### 7.4 参数追问策略

建议不要一次追问过多参数。可以按任务阶段分批追问：

第一轮：

- 几何来源
- 分析类型
- 求解器

第二轮：

- 材料
- 边界条件
- 载荷

第三轮：

- 网格
- 输出指标
- 是否执行

这样用户体验更好，也降低误填概率。

### 7.5 参数校验规则

必须至少支持以下校验：

- 类型校验：字符串、数字、布尔、数组、对象。
- 枚举校验：分析类型、单元类型、求解器类型。
- 单位校验：长度、力、压力、温度、时间。
- 范围校验：网格尺寸不能小于合理阈值，泊松比范围应合理。
- 依赖校验：如果选择疲劳分析，必须有载荷谱或循环载荷参数。
- 完整性校验：执行前所有必填参数必须存在。

建议新增 `CAEParameterValidator`，不要把校验逻辑全部放进 prompt。

---

## 8. 函数组合与流程规划设计

### 8.1 当前项目是否已支持

当前 `AgentRunner` 可以让 LLM 自主连续调用多个工具，已经具备“函数拼接”的基础能力。

例如，LLM 可以依次调用：

1. `cae_create_geometry`
2. `cae_generate_mesh`
3. `cae_apply_material`
4. `cae_apply_boundary_condition`
5. `cae_apply_load`
6. `cae_build_script`
7. `cae_run_simulation`

但这种自主规划不够稳定。CAE 流程有强顺序和强依赖，建议新增 `CAEPlanner`。

### 8.2 CAEPlan 数据结构

```python
class CAEPlanStep(BaseModel):
    step_id: str
    function_name: str
    inputs: dict
    depends_on: list[str] = []
    expected_output: str

class CAEPlan(BaseModel):
    task_id: str
    intent: CAEIntentResult
    steps: list[CAEPlanStep]
    final_output: Literal["python_script", "simulation_result", "report"]
    requires_user_confirmation_before_execute: bool = True
```

### 8.3 示例流程：静力分析

```text
用户目标：对支架做静力分析并执行

CAEPlan:
1. import_geometry
2. clean_geometry
3. assign_material
4. generate_mesh
5. create_static_step
6. apply_boundary_condition
7. apply_load
8. set_outputs
9. build_python_script
10. validate_python_script
11. run_simulation
12. extract_stress_displacement
13. generate_summary_report
```

### 8.4 示例流程：疲劳分析

```text
用户目标：基于已有静力结果评估疲劳寿命

CAEPlan:
1. load_previous_result
2. define_fatigue_material
3. define_load_spectrum
4. calculate_stress_range
5. run_fatigue_assessment
6. extract_damage
7. evaluate_life
8. generate_fatigue_report
```

### 8.5 计划生成方式

PoC 阶段：

- 由 LLM 根据提示词直接生成 plan JSON。
- `CAEPlanner` 只做 schema 校验。

正式阶段：

- 内置常见 workflow 模板。
- LLM 只负责选择模板和填参数。
- 对不常见任务再由 LLM 生成 plan。

推荐使用模板优先，因为 CAE 流程稳定性很重要。

---

## 9. Python 脚本生成设计

### 9.1 设计原则

最终 CAE 操作输出为 Python 脚本。建议不要让 LLM 直接一次性生成完整脚本并执行。

推荐方式：

1. 每个 CAE 函数返回脚本片段或结构化脚本 IR。
2. `CAEScriptBuilder` 按计划顺序组合脚本。
3. `CAEScriptValidator` 做静态检查。
4. 用户确认后再执行。

这样可控性和可审计性更好。

### 9.2 脚本片段模式

每个函数返回：

```json
{
  "ok": true,
  "function_name": "cae_generate_mesh",
  "script_fragment": "model.mesh.generate(size=2.0, element_type='tet')",
  "warnings": []
}
```

`CAEScriptBuilder` 负责拼接：

```python
from cae_software_api import Session

session = Session()
model = session.new_model()

# geometry
model.geometry.import_file(r"D:\cases\bracket.step")

# material
mat = model.materials.create("steel")
mat.elastic(E=210000, nu=0.3)

# mesh
model.mesh.generate(size=2.0, element_type="tet")

# boundary condition
model.boundary.fix(face="left_mounting_face")

# load
model.loads.force(face="right_hole", value=1000, direction=[0, -1, 0])

# solve
job = session.submit(model)
job.wait()
```

### 9.3 脚本 IR 模式

更推荐中长期使用脚本 IR，而不是直接拼字符串。

示例：

```json
{
  "operation": "mesh.generate",
  "args": {
    "size": 2.0,
    "element_type": "tet"
  }
}
```

然后由确定性的代码生成器生成 Python。

优点：

- 更安全。
- 更容易校验。
- 更容易支持多个 CAE 软件。
- 更容易做版本升级。

### 9.4 脚本生成工具

建议新增工具：

```text
cae_build_script
```

输入：

- `plan`
- `function_results`
- `solver_profile`
- `output_path`

输出：

- `script_path`
- `script_preview`
- `warnings`

### 9.5 脚本校验工具

建议新增工具：

```text
cae_validate_script
```

校验内容：

- Python 语法检查。
- 禁止危险 import，例如 `os`, `subprocess`, `shutil`，除非白名单允许。
- 禁止访问非 workspace 路径。
- 检查是否包含必要的 solver 初始化代码。
- 检查是否包含必要的保存/输出路径。
- 检查单位和参数范围。

注意：如果你的 CAE 软件脚本必须使用 `os` 或 `subprocess`，可以做 solver-specific 白名单，而不是完全禁止。

---

## 10. 仿真软件执行接口设计

### 10.1 当前项目是否已支持

当前项目有 `exec` 工具，可以执行外部命令。因此最小实现可以直接用：

```text
exec(command="cae_solver.exe -script generated.py")
```

但正式系统不建议直接让 LLM 构造命令。原因：

- 容易出现命令注入。
- 不方便记录 job_id。
- 不方便处理日志、超时和失败。
- 不方便接入许可证、集群队列或远程执行。

建议新增专用执行工具。

### 10.2 CAESimulatorExecutorTool

建议新增：

```text
cae_run_simulation
```

输入参数：

```json
{
  "script_path": "D:\\cases\\case001\\run.py",
  "solver": "custom_cae",
  "working_dir": "D:\\cases\\case001",
  "mode": "local",
  "timeout_seconds": 7200,
  "wait": true
}
```

输出：

```json
{
  "ok": true,
  "job_id": "case001-20260421-001",
  "status": "completed",
  "log_path": "D:\\cases\\case001\\solver.log",
  "result_dir": "D:\\cases\\case001\\results",
  "exit_code": 0,
  "warnings": []
}
```

### 10.3 执行模式

建议支持三种模式：

| 模式 | 说明 |
|---|---|
| `local_sync` | 本机同步执行，适合小算例和 PoC |
| `local_async` | 本机异步执行，返回 job_id |
| `remote_queue` | 提交到远程队列或 HPC |

### 10.4 作业状态查询工具

建议新增：

```text
cae_get_job_status
cae_cancel_job
cae_get_job_log
```

这样用户可以问：

- “刚才那个算例跑完了吗？”
- “帮我看一下求解日志有没有报错。”
- “停止当前仿真。”

### 10.5 与 Subagent 的关系

`nanobot` 当前已有 `SubagentManager`。对于长时间仿真，推荐：

- 主 Agent 负责参数确认和脚本生成。
- 子 Agent 或后台任务负责监控求解状态。
- 求解完成后通过系统消息通知主会话。

这可以复用现有 `Subagent` 机制，但正式生产建议仍引入专用 job store。

---

## 11. 后处理与结果解释设计

虽然用户当前重点提出的是 Python 脚本执行，但 CAE Agent 如果没有后处理能力，会停留在“自动写脚本”的层面。

建议新增后处理工具：

```text
cae_extract_result
cae_plot_contour
cae_plot_curve
cae_compare_result
cae_generate_report
```

示例输出：

```json
{
  "max_von_mises": {
    "value": 235.6,
    "unit": "MPa",
    "location": "fillet_3"
  },
  "max_displacement": {
    "value": 0.42,
    "unit": "mm",
    "location": "free_end"
  },
  "safety_factor": 1.52
}
```

不要让 LLM 直接从原始日志中猜结论。应先用工具提取结构化指标，再让 LLM 负责解释。

---

## 12. 对话流程设计

### 12.1 闲聊流程

```text
用户：你好，你能做什么？
系统：
1. IntentClassifier -> top_level=chat
2. 走原 nanobot AgentLoop
3. 不调用 CAE 工具
```

### 12.2 简单 CAE 问答流程

```text
用户：什么是四面体网格？
系统：
1. IntentClassifier -> top_level=chat 或 cae_qa
2. 不执行 CAE 函数
3. 返回解释
```

这类问题不应进入脚本生成。

### 12.3 CAE 操作但参数不足

```text
用户：帮我给这个模型划分网格。
系统：
1. 分类为 cae.mesh.generate_mesh
2. 识别缺失 geometry_path、mesh_size、element_type
3. 保存 CAETaskState
4. 向用户追问
```

返回：

```text
可以。请补充三个信息：

1. 模型文件路径是什么？
2. 希望的全局网格尺寸是多少？例如 2 mm。
3. 单元类型使用四面体、六面体还是软件默认？
```

### 12.4 CAE 操作且参数完整

```text
用户：对 D:\case\bracket.step 做静力分析，材料钢 E=210GPa, nu=0.3，左侧固定，右孔施加 1000N 向下力，网格 2mm，用 custom_cae 执行。
系统：
1. 分类为 workflow.run_static_analysis
2. 提取参数
3. 校验参数
4. 生成 CAEPlan
5. 调用 CAE 函数生成脚本片段
6. 构建 Python 脚本
7. 校验脚本
8. 询问用户是否执行，或根据配置自动执行
```

### 12.5 执行前确认

建议默认执行前确认：

```text
我已生成静力分析脚本：

- 几何：D:\case\bracket.step
- 材料：钢，E=210 GPa，nu=0.3
- 约束：左侧固定
- 载荷：右孔 1000 N，方向向下
- 网格：2 mm
- 求解器：custom_cae

脚本路径：D:\case\bracket_static\run.py

是否现在执行仿真？
```

只有用户确认后才调用 `cae_run_simulation`。

---

## 13. 提示词设计

### 13.1 当前项目是否只靠提示词即可

对于 PoC，可以只靠提示词实现大部分流程。

你可以新增一个 CAE Skill：

```text
workspace/skills/cae/SKILL.md
```

内容包括：

- 意图分类规则。
- CAE 函数调用规则。
- 参数不足时必须追问。
- 不允许猜测工程关键参数。
- 脚本执行前必须确认。

但对于正式系统，提示词只能作为辅助，不能替代显式模块。

### 13.2 CAE 系统提示词原则

建议加入以下规则：

```text
你是 CAE Agent。

当用户只是询问概念或闲聊时，不要调用 CAE 工具。

当用户要求执行 CAE 操作时，必须：
1. 判断 CAE 操作类别。
2. 检查是否存在匹配的 CAE skill；如果存在，应优先按照 skill 的成熟流程执行。
3. 选择合适的 CAE 函数或函数链。
4. 检查所需参数。
5. 如果缺少几何、材料、边界条件、载荷、网格、求解器等关键参数，必须先追问，不得猜测。
6. 只有参数完整时才能生成 Python 脚本。
7. 只有用户确认后才能执行仿真软件。
8. 执行结果必须基于工具返回的结构化结果，不得编造。
```

### 13.3 参数缺失追问提示词

```text
你需要根据 CAEFunctionSpec 判断缺少哪些必填参数。

追问规则：
- 一次最多追问 5 个问题。
- 优先追问阻塞后续流程的参数。
- 对每个参数给出单位或示例。
- 不要询问已经明确给出的参数。
- 如果用户使用模糊描述，要求其确认。
```

### 13.4 脚本生成提示词

```text
你只能根据 CAEPlan 和已验证参数生成 Python 脚本。

禁止：
- 使用未确认参数。
- 编造文件路径。
- 编造材料数据。
- 在脚本中执行任意系统命令。

必须：
- 使用指定 solver profile。
- 输出完整可执行 Python 脚本。
- 保留注释标明每个 CAEPlan step。
- 将结果输出到指定 result_dir。
```

### 13.5 CAE Skill 设计

对于成熟通用的 CAE 操作，建议写成独立 skill，而不是只写在总提示词中。

推荐目录：

```text
workspace/skills/standard-static-analysis/SKILL.md
workspace/skills/mesh-quality-check/SKILL.md
workspace/skills/fatigue-assessment/SKILL.md
workspace/skills/postprocess-report/SKILL.md
```

一个 CAE skill 建议包含以下内容：

```markdown
---
description: Standard static analysis workflow for CAE models.
metadata:
  nanobot:
    always: false
    cae:
      domains: ["workflow", "physics", "mesh", "postprocessing"]
      tasks: ["run_static_analysis"]
      supported_solvers: ["custom_cae"]
      required_tools:
        - cae_import_geometry
        - cae_assign_material
        - cae_generate_mesh
        - cae_apply_boundary_condition
        - cae_apply_load
        - cae_build_script
        - cae_run_simulation
---

# Standard Static Analysis

Use this skill when the user asks to run a static structural analysis.

## Required Inputs

- geometry file or geometry object
- material model
- boundary condition
- load definition
- mesh size or mesh strategy
- solver profile

## Workflow

1. Confirm missing required inputs.
2. Import or create geometry.
3. Assign material.
4. Generate mesh and check mesh quality.
5. Create static analysis step.
6. Apply constraints and loads.
7. Build Python script.
8. Validate script.
9. Ask user for execution confirmation.
10. Execute simulation.
11. Extract max stress, max displacement and safety factor.

## Rules

- Never guess material or load values.
- Never execute before user confirmation.
- Always report script path and result directory.
```

### 13.6 Skill 选择策略

当前项目已有 skill summary 注入机制，Agent 可以看到可用 skill 的名称、描述和路径，并在需要时读取 `SKILL.md`。这已经可以满足 PoC。

正式版建议新增 `CAESkillSelector`，不要完全依赖 LLM 自行选择 skill。

`CAESkillSelector` 的输入：

- `CAEIntentResult`
- 用户原始输入
- 当前 session 中的 `CAETaskState`
- 可用 skill 列表及其 metadata

输出：

```python
class CAESkillMatch(BaseModel):
    skill_name: str
    skill_path: str
    confidence: float
    reason: str
    required_tools: list[str] = []
    supported_solvers: list[str] = []
```

选择规则：

- 如果 skill metadata 中的 `domains` / `tasks` 与分类结果匹配，则提高优先级。
- 如果用户明确提到“标准静力分析”“疲劳评估”“网格质量检查”等名称，则优先匹配对应 skill。
- 如果 skill 要求的工具不存在，则不能直接执行，应提示缺少工具。
- 如果多个 skill 匹配，应选择置信度最高的一个，或询问用户选择。
- 如果没有 skill 匹配，则回退到 `CAEPlanner` 的通用流程规划。

### 13.7 Skill 与参数补全的关系

Skill 应该补充参数规则，而不是绕过参数规则。

例如 `standard-static-analysis` skill 中定义了必需输入：

- 几何
- 材料
- 约束
- 载荷
- 网格
- 求解器

那么 `CAESlotFillingManager` 应把这些 skill required inputs 合并到函数 schema 的 required parameters 中。最终缺失参数列表应来自：

```text
missing = function_required_parameters + skill_required_inputs - extracted_parameters
```

这样可以避免出现“函数 schema 没要求，但工程流程实际需要”的漏检问题。

### 13.8 Skill 与函数链的关系

Skill 可以定义推荐流程，但实际执行仍应映射为函数链。

示例：

```text
Skill workflow:
1. Import or create geometry
2. Assign material
3. Generate mesh
4. Apply constraints and loads
5. Build script
6. Execute simulation
```

Planner 映射为：

```json
[
  {"function_name": "cae_import_geometry"},
  {"function_name": "cae_assign_material"},
  {"function_name": "cae_generate_mesh"},
  {"function_name": "cae_apply_boundary_condition"},
  {"function_name": "cae_apply_load"},
  {"function_name": "cae_build_script"},
  {"function_name": "cae_run_simulation"}
]
```

如果某个 skill 只描述流程但没有对应工具，系统应返回：

```text
当前系统存在该 CAE skill，但缺少执行它所需的工具：cae_generate_mesh、cae_run_simulation。
请先注册这些 CAE 函数或 MCP 工具。
```

---

## 14. 配置设计

建议在 `nanobot/config/schema.py` 增加：

```python
class CAEConfig(Base):
    enable: bool = False
    mode: Literal["prompt", "router"] = "router"
    enable_skills: bool = True
    skill_match_threshold: float = 0.72
    require_confirmation_before_execute: bool = True
    default_solver: str = "custom_cae"
    script_output_dir: str = "cae_scripts"
    job_output_dir: str = "cae_jobs"
    allow_direct_exec: bool = False
    max_questions_per_turn: int = 5

class ToolsConfig(Base):
    ...
    cae: CAEConfig = Field(default_factory=CAEConfig)
```

示例配置：

```json
{
  "tools": {
    "restrictToWorkspace": true,
    "cae": {
      "enable": true,
      "mode": "router",
      "enableSkills": true,
      "skillMatchThreshold": 0.72,
      "requireConfirmationBeforeExecute": true,
      "defaultSolver": "custom_cae",
      "scriptOutputDir": "cae_scripts",
      "jobOutputDir": "cae_jobs",
      "allowDirectExec": false,
      "maxQuestionsPerTurn": 5
    }
  }
}
```

---

## 15. 推荐开发方案

### 15.1 低侵入 PoC 方案

适合 1 到 2 周内验证。

开发内容：

1. 新增 `workspace/skills/cae/SKILL.md` 或多个具体 CAE skill，例如 `standard-static-analysis`。
2. 新增若干 CAE Tool：
   - `cae_build_script`
   - `cae_run_simulation`
   - 若干领域操作工具
3. 在 `AgentLoop._register_default_tools()` 注册这些工具。
4. 使用现有 `SkillsLoader` 让 Agent 读取 CAE skill。
5. 使用现有 AgentRunner 让 LLM 按 skill 自动调用工具。
6. 强化提示词：命中 skill 时必须按 skill 流程执行，参数不足必须追问，执行前必须确认。

优点：

- 改造小。
- 能快速看到端到端效果。
- 可以复用现有 API/SDK。

缺点：

- 意图分类和参数补全不够稳定。
- 工程审计弱。
- 复杂流程容易漂移。

### 15.2 推荐正式方案

适合做可持续二开。

开发内容：

1. 新增 `nanobot/cae/taxonomy.py`。
2. 新增 `CAEIntentClassifier`。
3. 新增 `CAERouter`，在 `_process_message()` 早期拦截 CAE 消息。
4. 新增 `CAESkillSelector`，基于 taxonomy 和 skill metadata 选择成熟 CAE skill。
5. 新增 `CAEFunctionRegistry`。
6. 新增 `CAESlotFillingManager`。
7. 新增 `CAEPlanner`，支持以 skill 作为流程约束。
8. 新增 `CAEScriptBuilder`。
9. 新增 `CAEScriptValidator`。
10. 新增 `CAESimulatorExecutorTool`。
11. 新增 `CAEPostProcessor`。

优点：

- 稳定。
- 可审计。
- 易扩展。
- 更符合工程软件开发要求。

缺点：

- 初期开发量更大。
- 需要设计统一函数规范。

### 15.3 两阶段组合方案

最推荐：

第一阶段先做低侵入 PoC，验证：

- 函数注册方式是否合理。
- CAE skill 是否能正确约束函数链和追问策略。
- Python 脚本能否正确生成。
- 仿真软件执行接口是否顺畅。
- 用户参数追问体验是否可接受。

第二阶段再把 PoC 中稳定下来的函数、参数和流程固化为显式模块。

---

## 16. 关键开发任务拆解

### 16.1 任务一：定义 CAE taxonomy

产出：

- `nanobot/cae/taxonomy.py`
- 分类枚举
- 分类说明
- 典型 utterance 示例

验收标准：

- 能把常见请求分类到几何、网格、物理场、耦合、优化、寿命、疲劳、后处理。
- 能区分闲聊和 CAE 操作。

### 16.2 任务二：实现意图分类器

产出：

- `nanobot/cae/intent.py`
- `CAEIntentClassifier.classify(text, session_context)`

验收标准：

- 返回严格结构化结果。
- 支持 confidence。
- 低置信度时触发澄清。

### 16.3 任务三：实现 CAE Skill 选择器

产出：

- `nanobot/cae/skill_selector.py`
- `CAESkillMatch`
- Skill metadata 解析规则

验收标准：

- 能读取 workspace 中的 CAE skill。
- 能根据 `CAEIntentResult` 匹配对应 skill。
- 能判断 skill 依赖的 CAE Tool 是否已经注册。
- 没有可用 skill 时能回退到通用 planner。

### 16.4 任务四：实现 CAE 函数注册中心

产出：

- `nanobot/cae/registry.py`
- `CAEFunctionSpec`
- `CAEFunctionRegistry`

验收标准：

- 支持按 domain/task 查找函数。
- 支持把函数转换成 `Tool`。
- 支持从 manifest 加载函数描述。

### 16.5 任务五：实现参数槽位补全

产出：

- `nanobot/cae/slot_filling.py`
- `CAETaskState`
- `CAESlotFillingManager`

验收标准：

- 参数不足时不会执行。
- 可以多轮收集参数。
- 参数完整后自动进入 plan 阶段。

### 16.6 任务六：实现流程规划器

产出：

- `nanobot/cae/planner.py`
- 标准 workflow 模板

验收标准：

- 静力分析、网格划分、后处理至少各有一个可运行模板。
- 支持单函数任务和多函数链任务。
- 当命中 skill 时，能把 skill workflow 映射为函数链。

### 16.7 任务七：实现 Python 脚本生成

产出：

- `nanobot/cae/script_builder.py`
- `nanobot/cae/script_validator.py`

验收标准：

- 能生成完整 Python 脚本。
- 脚本路径固定在 workspace 下。
- 脚本执行前能通过语法和安全校验。

### 16.8 任务八：实现仿真软件执行工具

产出：

- `nanobot/cae/executor.py`
- `cae_run_simulation`
- `cae_get_job_status`
- `cae_get_job_log`

验收标准：

- 能调用指定 CAE 软件执行脚本。
- 能返回 job_id、日志路径、结果路径和状态。
- 能处理失败、超时和取消。

---

## 17. 推荐最小可行版本

MVP 建议只做一个完整闭环，不要一开始覆盖所有 CAE 类型。

建议选择：

> 参数化静力分析闭环

MVP 支持：

- 意图分类：闲聊 vs 静力分析 vs 网格 vs 后处理。
- Skill：至少提供一个 `standard-static-analysis` skill，用于约束静力分析标准流程。
- 参数收集：
  - 几何文件
  - 材料
  - 约束
  - 载荷
  - 网格尺寸
  - 求解器
- 函数链：
  - import geometry
  - assign material
  - generate mesh
  - apply boundary condition
  - apply load
  - create static step
  - build script
  - run simulation
  - extract result
- 输出：
  - Python 脚本
  - 执行日志
  - 关键结果摘要

MVP 不建议一开始支持：

- 复杂多物理场耦合
- 自动优化
- 疲劳寿命全流程
- 多软件统一抽象
- HPC 调度

这些应在基础闭环稳定后扩展。

---

## 18. 风险与控制措施

### 18.1 参数幻觉风险

风险：

- LLM 可能补全用户没有提供的材料、载荷或边界条件。

控制：

- 必填参数缺失时强制追问。
- 执行前显示参数摘要并要求确认。
- 对关键参数设置 `requires_confirmation=True`。

### 18.2 错误函数调用风险

风险：

- LLM 调用不适合当前意图的函数。
- LLM 命中了不适合当前任务的 skill，导致流程选择错误。

控制：

- 使用显式 IntentClassifier 和 Planner。
- 使用 `CAESkillSelector` 对 skill 的 domain、task、required tools 和 solver 支持进行校验。
- Tool 层校验 domain/task。
- Plan 执行前做依赖检查。

### 18.3 脚本安全风险

风险：

- 生成脚本可能包含危险代码。

控制：

- 使用 IR 到 Python 的确定性生成器。
- 静态 AST 校验。
- workspace 路径限制。
- 执行前用户确认。

### 18.4 仿真执行风险

风险：

- 求解器长时间运行、失败、占用资源或许可证。

控制：

- 使用专用 executor。
- 设置超时。
- 保存日志。
- 支持状态查询和取消。
- 必要时对接外部作业队列。

### 18.5 结果解释风险

风险：

- LLM 可能编造后处理结论。

控制：

- 后处理工具输出结构化结果。
- LLM 只能解释工具返回结果。
- 报告中保留数据来源和文件路径。

---

## 19. 建议实施路线

### 第一阶段：PoC

时间目标：1 到 2 周。

任务：

- 新增 CAE Skill。
- 手写 5 到 8 个 CAE Tool。
- 注册到 `ToolRegistry`。
- 生成 Python 脚本。
- 调用仿真软件执行。
- 跑通一个静力分析案例。

### 第二阶段：显式状态机

时间目标：2 到 4 周。

任务：

- 新增意图分类器。
- 新增 CAE Skill 选择器。
- 新增参数槽位状态。
- 新增多轮参数追问。
- 新增流程模板，并支持从 skill workflow 生成函数链。
- 增加执行前确认。

### 第三阶段：工程化

时间目标：4 到 8 周。

任务：

- 新增 CAEFunctionRegistry。
- 支持 CAE skill metadata 规范。
- 支持 manifest 注册。
- 支持 job store。
- 支持后处理结构化结果。
- 支持报告生成。
- 增加测试覆盖。

### 第四阶段：生产增强

时间目标：视业务复杂度而定。

任务：

- 接入数据库。
- 接入对象存储。
- 接入远程队列或 HPC。
- 支持权限和审计。
- 支持多求解器 profile。
- 支持历史算例检索。

---

## 20. 最终建议

`nanobot` 已经具备改造成 CAE Agent 的核心 Agent 基础设施，尤其是工具调用、会话、多轮 Agent 循环、MCP、Shell 执行和 API/SDK 入口。因此，不需要重写 Agent runtime。

但你要实现的 CAE Agent 不是简单“加几个 prompt”就能可靠完成的。建议采用以下判断：

- **闲聊识别、基础分类、参数不足时追问**：PoC 阶段可以先通过提示词和 Skill 实现。
- **成熟 CAE 通用操作**：当前 Skill 系统已经支持，适合沉淀标准流程、软件 API 使用规范、企业建模规范和后处理规范；正式版建议新增 `CAESkillSelector` 做显式匹配。
- **CAE 函数调用**：当前 Tool 系统已经支持，短期直接注册 Tool 即可。
- **复杂多函数流程编排**：建议新增 `CAEPlanner`，并让它优先参考已命中的 CAE skill，不要完全交给 LLM 自由调用。
- **参数补全多轮对话**：建议新增 `CAESlotFillingManager`，不要只靠历史上下文。
- **Python 脚本生成**：建议新增 `CAEScriptBuilder`，函数返回脚本片段或 IR。
- **仿真软件执行**：建议新增专用 `CAESimulatorExecutorTool`，不要直接让 LLM 拼 shell 命令。

推荐最终架构是：

> `nanobot` 负责 Agent 运行时、Skill 加载和通用工具编排；新增 `nanobot/cae` 负责 CAE 领域意图、CAE skill 选择、参数、函数注册、流程规划、脚本生成、仿真执行和后处理。

这样既能复用现有项目优势，又能保证 CAE 工作流的确定性、可控性和工程可审计性。
