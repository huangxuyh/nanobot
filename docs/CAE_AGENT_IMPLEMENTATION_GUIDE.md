# CAE Agent 二次开发实施文档

## 1. 文档目标

本文档是对 `nanobot` 进行二次开发、实现 CAE Agent 的工程实施指南。

前置分析报告已经说明了总体架构和能力边界。本文进一步细化到：

- 应新增哪些模块和文件。
- 应如何接入现有 `AgentLoop`、`ToolRegistry`、`SkillsLoader`、`SessionManager`。
- 意图分类、Skill 选择、函数注册、参数补全、多轮确认、函数编排、Python 脚本生成、仿真软件执行如何落地。
- 每个模块的职责、核心类、关键接口、数据结构和测试建议。
- 如何先做 MVP，再逐步工程化。

本文不要求一次性完成所有功能。推荐按阶段实现，先跑通一个最小可行的 CAE 静力分析闭环，再逐步扩展到更多 CAE 任务。

---

## 2. 推荐目标

本次二次开发的目标不是重写 `nanobot`，而是在其现有 Agent 能力上新增一层 CAE 专用业务编排层。

最终系统应具备以下主流程：

```text
用户输入
  |
  v
CAE Router
  |
  +-- 闲聊 / 普通问答 -> 原 nanobot AgentLoop
  |
  +-- CAE 操作
        |
        v
  Intent Classifier
        |
        v
  Skill Selector
        |
        v
  Function Registry
        |
        v
  Slot Filling / 参数补全
        |
        +-- 参数不足 -> 追问用户 -> 保存 CAETaskState -> 等待下一轮
        |
        +-- 参数完整
              |
              v
        Planner / 函数链规划
              |
              v
        Script Builder / Python 脚本生成
              |
              v
        Script Validator / 脚本校验
              |
              +-- 需要确认 -> 询问用户是否执行
              |
              v
        Simulator Executor / 仿真软件执行
              |
              v
        PostProcessor / 结果提取与解释
              |
              v
        返回结果
```

---

## 3. 当前项目可复用能力

### 3.1 可直接复用

| 能力 | 当前实现 | 用法 |
|---|---|---|
| Agent 主循环 | `nanobot/agent/loop.py` | 继续作为入口和会话处理层 |
| LLM 工具调用循环 | `nanobot/agent/runner.py` | CAE 工具仍可作为 Tool 被 LLM 调用 |
| Tool 系统 | `nanobot/agent/tools/base.py`、`registry.py` | CAE 操作函数可实现为 Tool |
| Skill 系统 | `nanobot/agent/skills.py` | 成熟 CAE 流程可写成 workspace skill |
| Session | `nanobot/session/manager.py` | 保存多轮参数补全状态 |
| 文件工具 | `read_file`、`write_file`、`edit_file` | 读写脚本、配置、结果摘要 |
| Shell 工具 | `exec` | PoC 阶段可执行仿真命令，正式版建议封装 executor |
| MCP | `nanobot/agent/tools/mcp.py` | 可接入外部 CAE 服务 |
| API/SDK | `nanobot/api/server.py`、`nanobot/nanobot.py` | 可对接前端或业务系统 |

### 3.2 需要新增

| 模块 | 是否已有 | 处理方式 |
|---|---|---|
| CAE 意图分类 | 没有 | 新增 |
| CAE skill 显式选择 | 没有 | 新增 |
| CAE 函数注册中心 | 没有 | 新增 |
| 参数槽位状态机 | 没有 | 新增 |
| CAE 流程规划 | 没有 | 新增 |
| Python 脚本构建器 | 没有 | 新增 |
| 脚本安全校验 | 没有 | 新增 |
| 仿真软件执行接口 | 没有 | 新增 |
| CAE 结果结构化后处理 | 没有 | 新增 |

---

## 4. 新增目录结构

建议新增 `nanobot/cae/`，将 CAE 专用逻辑与通用 Agent runtime 解耦。

```text
nanobot/
  cae/
    __init__.py
    taxonomy.py
    schemas.py
    intent.py
    skill_selector.py
    registry.py
    slot_filling.py
    planner.py
    script_builder.py
    script_validator.py
    executor.py
    postprocess.py
    router.py
    tools.py
    prompts/
      intent_classifier.md
      skill_selection.md
      slot_filling.md
      planner.md
      script_generation.md
      result_interpretation.md
    manifests/
      standard_static_analysis.yaml
```

建议新增测试目录：

```text
tests/
  cae/
    test_taxonomy.py
    test_intent_classifier.py
    test_skill_selector.py
    test_registry.py
    test_slot_filling.py
    test_planner.py
    test_script_builder.py
    test_script_validator.py
    test_executor.py
    test_router.py
```

建议新增 workspace 示例：

```text
examples/
  cae/
    workspace/
      skills/
        standard-static-analysis/
          SKILL.md
        mesh-quality-check/
          SKILL.md
      cases/
        static_bracket/
```

---

## 5. 配置改造

### 5.1 修改文件

修改：

```text
nanobot/config/schema.py
```

### 5.2 新增配置模型

建议新增：

```python
class CAEConfig(Base):
    enable: bool = False
    mode: Literal["prompt", "router"] = "router"
    enable_skills: bool = True
    skill_match_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    intent_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    require_confirmation_before_execute: bool = True
    default_solver: str = "custom_cae"
    script_output_dir: str = "cae_scripts"
    job_output_dir: str = "cae_jobs"
    allow_direct_exec: bool = False
    max_questions_per_turn: int = Field(default=5, ge=1, le=10)
    max_script_preview_chars: int = Field(default=8000, ge=1000)
```

在 `ToolsConfig` 中加入：

```python
cae: CAEConfig = Field(default_factory=CAEConfig)
```

### 5.3 配置示例

```json
{
  "tools": {
    "restrictToWorkspace": true,
    "cae": {
      "enable": true,
      "mode": "router",
      "enableSkills": true,
      "skillMatchThreshold": 0.72,
      "intentConfidenceThreshold": 0.65,
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

### 5.4 兼容策略

- 默认 `enable=false`，不影响现有用户。
- 只有开启 `tools.cae.enable` 时才启用 CAE Router。
- PoC 阶段可设置 `mode="prompt"`，只加载 CAE skill 和 CAE tools。
- 正式阶段使用 `mode="router"`，走显式分类和状态机。

---

## 6. 数据结构设计

### 6.1 `schemas.py`

新增：

```text
nanobot/cae/schemas.py
```

集中定义 CAE 相关 Pydantic 模型。

### 6.2 意图结果

```python
from typing import Literal, Any
from pydantic import BaseModel, Field

TopLevelIntent = Literal["chat", "cae", "project_management", "unknown"]

class CAEIntentResult(BaseModel):
    top_level: TopLevelIntent
    cae_domain: str | None = None
    cae_task: str | None = None
    cae_subtask: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    requires_tools: bool = False
    suggested_operations: list[str] = Field(default_factory=list)
    extracted_entities: dict[str, Any] = Field(default_factory=dict)
    missing_information_hint: list[str] = Field(default_factory=list)
    user_goal_summary: str = ""
```

### 6.3 Skill 匹配结果

```python
class CAESkillMatch(BaseModel):
    skill_name: str
    skill_path: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    required_tools: list[str] = Field(default_factory=list)
    supported_solvers: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
```

### 6.4 函数定义

```python
class CAEParameterSpec(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""
    unit: str | None = None
    enum: list[str] | None = None
    default: Any | None = None
    ask_when_missing: str | None = None
    examples: list[str] = Field(default_factory=list)

class CAEFunctionSpec(BaseModel):
    name: str
    display_name: str
    domain: str
    task: str
    description: str
    parameters: list[CAEParameterSpec]
    output_type: Literal["script_fragment", "script", "result", "job_id", "metadata"]
    supported_solvers: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    safety_level: Literal["read", "write_script", "execute"] = "write_script"
```

### 6.5 函数执行结果

```python
class CAEFunctionResult(BaseModel):
    ok: bool
    function_name: str
    script_fragment: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

### 6.6 参数补全状态

```python
class CAETaskState(BaseModel):
    task_id: str
    status: Literal[
        "collecting_params",
        "awaiting_confirmation",
        "ready",
        "script_built",
        "executing",
        "completed",
        "failed",
    ]
    intent: CAEIntentResult
    selected_skill: str | None = None
    selected_functions: list[str] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    slot_questions: dict[str, str] = Field(default_factory=dict)
    confirmations: dict[str, bool] = Field(default_factory=dict)
    plan: "CAEPlan | None" = None
    script_path: str | None = None
    job_id: str | None = None
    last_user_message: str = ""
```

### 6.7 计划结构

```python
class CAEPlanStep(BaseModel):
    step_id: str
    function_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""

class CAEPlan(BaseModel):
    task_id: str
    intent: CAEIntentResult
    skill_name: str | None = None
    steps: list[CAEPlanStep]
    final_output: Literal["python_script", "simulation_result", "report"]
    requires_user_confirmation_before_execute: bool = True
```

### 6.8 执行结果

```python
class CAEJobResult(BaseModel):
    ok: bool
    job_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "timeout"]
    script_path: str
    working_dir: str
    log_path: str | None = None
    result_dir: str | None = None
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

---

## 7. CAE Taxonomy 实现

### 7.1 新增文件

```text
nanobot/cae/taxonomy.py
```

### 7.2 推荐定义

```python
CAE_DOMAINS = {
    "geometry": {
        "description": "几何建模、几何导入、几何清理、参数化几何",
        "tasks": ["create_geometry", "import_cad", "clean_geometry", "parameterize_geometry"],
    },
    "mesh": {
        "description": "网格划分、网格质量检查、局部加密",
        "tasks": ["generate_mesh", "check_mesh_quality", "refine_mesh"],
    },
    "physics": {
        "description": "材料、边界条件、载荷、物理场设置",
        "tasks": ["assign_material", "apply_boundary_condition", "apply_load", "define_contact"],
    },
    "coupling": {
        "description": "多物理场耦合、流固耦合、热结构耦合",
        "tasks": ["setup_thermal_structural", "setup_fsi", "map_fields"],
    },
    "optimization": {
        "description": "参数优化、拓扑优化、形状优化",
        "tasks": ["define_design_variables", "define_objective", "run_optimization"],
    },
    "life_assessment": {
        "description": "寿命评估、可靠性、耐久性",
        "tasks": ["setup_life_model", "evaluate_life"],
    },
    "fatigue": {
        "description": "疲劳载荷、S-N 曲线、疲劳损伤",
        "tasks": ["define_fatigue_load", "calculate_damage", "evaluate_safety_factor"],
    },
    "postprocessing": {
        "description": "结果提取、云图、曲线、报告生成",
        "tasks": ["extract_result", "plot_contour", "plot_curve", "generate_report"],
    },
    "workflow": {
        "description": "完整仿真流程编排",
        "tasks": ["run_static_analysis", "run_modal_analysis", "run_thermal_analysis", "run_full_pipeline"],
    },
    "execution": {
        "description": "求解器执行、状态查询、日志分析",
        "tasks": ["run_simulation", "get_job_status", "analyze_log"],
    },
}
```

### 7.3 辅助函数

```python
def is_valid_domain(domain: str) -> bool:
    return domain in CAE_DOMAINS

def is_valid_task(domain: str, task: str) -> bool:
    return task in CAE_DOMAINS.get(domain, {}).get("tasks", [])

def list_all_operations() -> list[str]:
    return [
        f"{domain}.{task}"
        for domain, meta in CAE_DOMAINS.items()
        for task in meta["tasks"]
    ]
```

### 7.4 测试建议

测试文件：

```text
tests/cae/test_taxonomy.py
```

测试点：

- 所有 domain 均有 description。
- 所有 domain 至少有一个 task。
- `is_valid_domain()` 正常工作。
- `is_valid_task()` 正常工作。

---

## 8. 意图分类模块实现

### 8.1 新增文件

```text
nanobot/cae/intent.py
nanobot/cae/prompts/intent_classifier.md
```

### 8.2 模块职责

`CAEIntentClassifier` 负责将用户输入分类为：

- 闲聊 / 普通问答。
- CAE 操作。
- 项目管理或作业查询。
- 未知。

对于 CAE 操作，还应输出：

- domain
- task
- subtask
- 置信度
- 初步抽取的参数实体
- 推荐操作函数

### 8.3 实现策略

建议先实现“规则 + LLM”混合分类：

1. 规则层识别明显关键词。
2. 如果规则置信度高，直接返回。
3. 如果规则置信度中等或低，调用 LLM 返回 JSON。
4. 校验 JSON，失败则返回 `unknown`。

### 8.4 类接口

```python
class CAEIntentClassifier:
    def __init__(self, provider, model: str, confidence_threshold: float = 0.65):
        self.provider = provider
        self.model = model
        self.confidence_threshold = confidence_threshold

    async def classify(
        self,
        text: str,
        *,
        session_context: list[dict] | None = None,
    ) -> CAEIntentResult:
        rule_result = self._rule_classify(text)
        if rule_result and rule_result.confidence >= 0.9:
            return rule_result
        llm_result = await self._llm_classify(text, session_context=session_context)
        return self._merge(rule_result, llm_result)
```

### 8.5 规则分类示例

```python
KEYWORD_RULES = {
    "mesh": ["网格", "划分网格", "mesh", "单元", "网格质量"],
    "geometry": ["几何", "CAD", "step", "iges", "建模", "导入模型"],
    "physics": ["材料", "边界条件", "载荷", "约束", "压力", "温度"],
    "fatigue": ["疲劳", "S-N", "寿命", "damage", "循环载荷"],
    "postprocessing": ["后处理", "云图", "应力", "位移", "结果", "报告"],
    "execution": ["执行", "求解", "运行", "提交任务", "job", "日志"],
}
```

### 8.6 LLM 分类提示词

`intent_classifier.md` 示例：

```markdown
你是 CAE Agent 的意图分类器。

请把用户输入分类为严格 JSON，不要输出解释。

一级分类：
- chat
- cae
- project_management
- unknown

CAE domain：
- geometry
- mesh
- physics
- coupling
- optimization
- life_assessment
- fatigue
- postprocessing
- workflow
- execution

返回 JSON：
{
  "top_level": "...",
  "cae_domain": "... or null",
  "cae_task": "... or null",
  "cae_subtask": "... or null",
  "confidence": 0.0,
  "requires_tools": true,
  "suggested_operations": [],
  "extracted_entities": {},
  "missing_information_hint": [],
  "user_goal_summary": ""
}
```

### 8.7 测试建议

测试文件：

```text
tests/cae/test_intent_classifier.py
```

测试样例：

- “你好” -> `chat`
- “什么是四面体网格” -> `chat` 或 `cae_qa`，不执行工具
- “帮我划分网格” -> `cae.mesh.generate_mesh`
- “对这个支架做静力分析” -> `cae.workflow.run_static_analysis`
- “查看刚才任务状态” -> `project_management` 或 `cae.execution.get_job_status`

---

## 9. CAE Skill 选择器实现

### 9.1 新增文件

```text
nanobot/cae/skill_selector.py
nanobot/cae/prompts/skill_selection.md
```

### 9.2 当前项目已有能力

`nanobot` 已有 `SkillsLoader`：

- 能发现 `workspace/skills/<skill>/SKILL.md`。
- 能发现 `nanobot/skills/<skill>/SKILL.md`。
- 能解析 frontmatter。
- 能构建 skill summary 注入上下文。

但当前缺少“按 CAE 意图显式选择 skill”的逻辑。因此新增 `CAESkillSelector`。

### 9.3 CAE Skill frontmatter 规范

建议所有 CAE skill 使用以下格式：

```markdown
---
description: Standard static analysis workflow.
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
      required_inputs:
        - geometry
        - material
        - boundary_condition
        - load
        - mesh_size
        - solver
---
```

### 9.4 类接口

```python
class CAESkillSelector:
    def __init__(self, skills_loader: SkillsLoader, registry: ToolRegistry, threshold: float = 0.72):
        self.skills_loader = skills_loader
        self.registry = registry
        self.threshold = threshold

    def select(
        self,
        intent: CAEIntentResult,
        user_text: str,
    ) -> CAESkillMatch | None:
        candidates = self._collect_candidates(intent)
        scored = [self._score(candidate, intent, user_text) for candidate in candidates]
        best = max(scored, key=lambda x: x.confidence, default=None)
        if not best or best.confidence < self.threshold:
            return None
        self._validate_required_tools(best)
        return best
```

### 9.5 匹配规则

评分建议：

| 条件 | 加分 |
|---|---:|
| skill metadata domain 命中 | +0.35 |
| skill metadata task 命中 | +0.35 |
| 用户文本命中 skill 名称或 description | +0.15 |
| 求解器匹配 | +0.1 |
| 所需工具全部存在 | +0.05 |

如果所需工具缺失，不应直接执行，应返回明确错误或降级。

### 9.6 所需工具校验

```python
def _validate_required_tools(self, match: CAESkillMatch) -> None:
    missing = [name for name in match.required_tools if not self.registry.has(name)]
    if missing:
        raise MissingCAEToolsError(missing)
```

### 9.7 Skill 读取策略

- PoC：让 Agent 自己通过 `read_file` 读取 skill。
- 正式版：`CAESkillSelector` 读取 skill metadata，`CAEPlanner` 读取 skill body。

### 9.8 测试建议

测试文件：

```text
tests/cae/test_skill_selector.py
```

测试点：

- 可读取 workspace skill。
- domain/task 匹配时能选中。
- 低置信度时返回 None。
- required_tools 缺失时返回错误。
- 同名 workspace skill 优先于 builtin skill。

---

## 10. CAE 函数注册中心实现

### 10.1 新增文件

```text
nanobot/cae/registry.py
nanobot/cae/manifests/
```

### 10.2 目标

`CAEFunctionRegistry` 负责管理 CAE 操作函数，支持：

- 注册 Python 函数。
- 从 manifest 加载函数定义。
- 按 domain/task 查询。
- 转换为 `nanobot Tool`。
- 校验函数参数。
- 给 `CAEPlanner` 和 `CAESlotFillingManager` 提供参数信息。

### 10.3 类接口

```python
class CAEFunctionRegistry:
    def __init__(self):
        self._specs: dict[str, CAEFunctionSpec] = {}
        self._handlers: dict[str, Callable[..., Awaitable[CAEFunctionResult]]] = {}

    def register(
        self,
        spec: CAEFunctionSpec,
        handler: Callable[..., Awaitable[CAEFunctionResult]],
    ) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> CAEFunctionSpec | None:
        return self._specs.get(name)

    def find_by_intent(self, domain: str, task: str) -> list[CAEFunctionSpec]:
        return [
            spec for spec in self._specs.values()
            if spec.domain == domain and spec.task == task
        ]

    async def execute(self, name: str, params: dict[str, Any]) -> CAEFunctionResult:
        spec = self._specs[name]
        self.validate_params(spec, params)
        return await self._handlers[name](**params)
```

### 10.4 转换为 Tool

可实现 `CAEFunctionTool`：

```python
class CAEFunctionTool(Tool):
    def __init__(self, registry: CAEFunctionRegistry, spec: CAEFunctionSpec):
        self._registry = registry
        self._spec = spec

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def parameters(self) -> dict[str, Any]:
        return cae_spec_to_json_schema(self._spec)

    async def execute(self, **kwargs: Any) -> str:
        result = await self._registry.execute(self._spec.name, kwargs)
        return result.model_dump_json()
```

### 10.5 manifest 示例

```yaml
name: cae_generate_mesh
display_name: Generate Mesh
domain: mesh
task: generate_mesh
description: Generate a mesh script fragment.
output_type: script_fragment
supported_solvers:
  - custom_cae
parameters:
  - name: geometry_id
    type: string
    required: true
    description: Geometry object identifier.
    ask_when_missing: "请提供要划分网格的几何对象或几何文件路径。"
  - name: global_size
    type: number
    required: true
    unit: mm
    description: Global mesh size.
    ask_when_missing: "请提供全局网格尺寸，例如 2 mm。"
  - name: element_type
    type: string
    required: false
    enum: ["tet", "hex", "shell", "beam"]
    default: "tet"
```

### 10.6 集成到 `AgentLoop`

短期：

```python
from nanobot.cae.tools import register_cae_tools

def _register_default_tools(self) -> None:
    ...
    if getattr(self.tools_config.cae, "enable", False):
        register_cae_tools(self.tools, self.workspace, self.tools_config.cae)
```

注意：当前 `AgentLoop.__init__` 中 `tools_config` 是局部变量 `_tc`，如果后续要在其他方法使用，建议保存：

```python
self.tools_config = _tc
```

### 10.7 测试建议

测试文件：

```text
tests/cae/test_registry.py
```

测试点：

- 注册函数。
- 按 domain/task 查询。
- manifest 加载。
- 转换 JSON Schema。
- 参数缺失时报错。

---

## 11. 参数补全实现

### 11.1 新增文件

```text
nanobot/cae/slot_filling.py
nanobot/cae/prompts/slot_filling.md
```

### 11.2 职责

`CAESlotFillingManager` 负责：

- 从用户输入中抽取参数。
- 合并历史参数状态。
- 根据函数 schema 和 skill required inputs 判断缺失参数。
- 生成追问问题。
- 在多轮对话中更新 `CAETaskState`。
- 参数完整后推进到 `ready`。

### 11.3 状态保存

PoC 阶段可保存到：

```python
session.metadata["cae_pending_task"] = task_state.model_dump()
```

正式阶段建议保存到文件：

```text
workspace/cae/tasks/<task_id>.json
```

推荐正式方式，因为 CAE 任务可能很长，且需要审计。

### 11.4 类接口

```python
class CAESlotFillingManager:
    def __init__(
        self,
        registry: CAEFunctionRegistry,
        max_questions_per_turn: int = 5,
    ):
        self.registry = registry
        self.max_questions_per_turn = max_questions_per_turn

    async def start_or_update(
        self,
        *,
        user_text: str,
        intent: CAEIntentResult,
        selected_skill: CAESkillMatch | None,
        selected_functions: list[str],
        existing_state: CAETaskState | None = None,
    ) -> CAETaskState:
        slots = dict(existing_state.slots) if existing_state else {}
        extracted = await self.extract_slots(user_text, intent, selected_functions)
        slots.update(extracted)
        missing = self.find_missing_slots(slots, selected_skill, selected_functions)
        questions = self.build_questions(missing, selected_skill, selected_functions)
        return CAETaskState(...)
```

### 11.5 缺失参数计算

缺失参数来源：

```text
函数必填参数 + skill required_inputs - 已抽取参数
```

示例：

```python
def find_missing_slots(
    self,
    slots: dict[str, Any],
    skill: CAESkillMatch | None,
    function_names: list[str],
) -> list[str]:
    required = set()
    for name in function_names:
        spec = self.registry.get(name)
        required.update(p.name for p in spec.parameters if p.required)
    if skill:
        required.update(self._skill_required_inputs(skill))
    return [name for name in sorted(required) if not self._has_valid_value(slots, name)]
```

### 11.6 追问生成

优先使用函数参数的 `ask_when_missing`，其次使用 skill 中的 required input 描述。

示例输出：

```text
要继续生成静力分析脚本，还需要确认以下信息：

1. 几何文件路径是什么？例如 D:\cases\bracket.step。
2. 材料参数是什么？例如 E=210GPa, nu=0.3。
3. 载荷大小、方向和施加位置是什么？
```

### 11.7 用户确认状态

执行前状态：

```python
state.status = "awaiting_confirmation"
state.confirmations["execute_simulation"] = False
```

用户回复“执行”、“确认”、“可以运行”后：

```python
state.confirmations["execute_simulation"] = True
```

### 11.8 测试建议

测试文件：

```text
tests/cae/test_slot_filling.py
```

测试点：

- 首轮参数不足时生成追问。
- 第二轮补充参数后状态更新。
- skill required inputs 能参与缺失参数判断。
- 参数完整后状态变为 `ready`。
- 执行前确认状态正确。

---

## 12. Planner 实现

### 12.1 新增文件

```text
nanobot/cae/planner.py
nanobot/cae/prompts/planner.md
```

### 12.2 职责

`CAEPlanner` 负责把用户目标、意图结果、已选 skill 和参数状态转为函数执行计划。

计划应包含：

- 函数顺序。
- 每步输入。
- 依赖关系。
- 最终输出类型。
- 是否需要执行前确认。

### 12.3 规划策略

推荐优先级：

1. 如果有已选 skill，优先从 skill workflow 映射函数链。
2. 如果没有 skill，但命中标准 workflow，使用内置模板。
3. 如果没有模板，再调用 LLM 生成计划 JSON。
4. 对所有计划做 schema 校验和函数存在性校验。

### 12.4 内置模板示例

```python
STATIC_ANALYSIS_TEMPLATE = [
    "cae_import_geometry",
    "cae_assign_material",
    "cae_generate_mesh",
    "cae_create_static_step",
    "cae_apply_boundary_condition",
    "cae_apply_load",
    "cae_set_outputs",
    "cae_build_script",
    "cae_validate_script",
]
```

如果用户要求执行，则追加：

```python
"cae_run_simulation"
```

如果用户要求结果摘要，则追加：

```python
"cae_extract_result",
"cae_generate_report"
```

### 12.5 类接口

```python
class CAEPlanner:
    def __init__(self, registry: CAEFunctionRegistry):
        self.registry = registry

    async def build_plan(
        self,
        state: CAETaskState,
        skill_body: str | None = None,
    ) -> CAEPlan:
        if state.selected_skill and skill_body:
            plan = self._plan_from_skill(state, skill_body)
        else:
            plan = self._plan_from_template_or_llm(state)
        self._validate_plan(plan)
        return plan
```

### 12.6 测试建议

测试文件：

```text
tests/cae/test_planner.py
```

测试点：

- 静力分析能生成固定函数链。
- skill workflow 能映射为函数链。
- 缺失函数时报错。
- plan 中 step_id 唯一。
- dependencies 合法。

---

## 13. Script Builder 实现

### 13.1 新增文件

```text
nanobot/cae/script_builder.py
nanobot/cae/prompts/script_generation.md
```

### 13.2 设计原则

不要直接让 LLM 一次性写完整脚本并执行。

推荐：

- CAE 函数返回脚本片段或 IR。
- `CAEScriptBuilder` 组合脚本。
- `CAEScriptValidator` 校验脚本。
- 执行前显示摘要和路径。

### 13.3 类接口

```python
class CAEScriptBuilder:
    def __init__(self, workspace: Path, script_output_dir: str):
        self.workspace = workspace
        self.script_output_dir = script_output_dir

    def build(
        self,
        *,
        task_state: CAETaskState,
        plan: CAEPlan,
        function_results: list[CAEFunctionResult],
        solver_profile: str,
    ) -> Path:
        script = self._render_script(...)
        path = self._script_path(task_state.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        return path
```

### 13.4 脚本结构建议

```python
# Auto-generated by nanobot CAE Agent
# task_id: ...
# solver: custom_cae

from custom_cae_api import Session

def main():
    session = Session()
    model = session.new_model()

    # Step 1: import geometry
    ...

    # Step 2: assign material
    ...

    # Step 3: generate mesh
    ...

    # Step 4: apply load and boundary condition
    ...

    # Step 5: solve or save model
    ...

if __name__ == "__main__":
    main()
```

### 13.5 路径规范

所有脚本必须写到 workspace 下：

```text
workspace/cae/scripts/<task_id>/run.py
```

所有结果必须写到：

```text
workspace/cae/jobs/<task_id>/
```

### 13.6 测试建议

测试文件：

```text
tests/cae/test_script_builder.py
```

测试点：

- 能生成脚本文件。
- 路径位于 workspace 内。
- 函数片段顺序正确。
- task_id 出现在脚本注释中。

---

## 14. Script Validator 实现

### 14.1 新增文件

```text
nanobot/cae/script_validator.py
```

### 14.2 校验内容

建议至少做：

- Python 语法检查。
- AST 危险节点检查。
- import 白名单检查。
- 路径访问检查。
- 必要入口检查。
- 禁止任意 shell 命令。

### 14.3 类接口

```python
class CAEScriptValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class CAEScriptValidator:
    def __init__(self, workspace: Path, allowed_imports: set[str]):
        self.workspace = workspace
        self.allowed_imports = allowed_imports

    def validate(self, script_path: Path) -> CAEScriptValidationResult:
        text = script_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return CAEScriptValidationResult(ok=False, errors=[str(exc)])
        return self._validate_ast(tree)
```

### 14.4 危险 import 建议

默认禁止：

- `subprocess`
- `shutil`
- `socket`
- `requests`
- `urllib`
- `pathlib` 的任意外部路径操作

注意：如果你的 CAE 软件 Python API 必须使用某些模块，应做 solver profile 白名单，而不是硬编码一刀切。

### 14.5 测试建议

测试文件：

```text
tests/cae/test_script_validator.py
```

测试点：

- 合法脚本通过。
- 语法错误失败。
- 危险 import 失败。
- `subprocess.Popen` 失败。
- workspace 外路径访问失败。

---

## 15. 仿真软件执行器实现

### 15.1 新增文件

```text
nanobot/cae/executor.py
```

### 15.2 职责

`CAESimulatorExecutor` 负责调用仿真软件执行脚本。

不要让 LLM 直接拼接 shell 命令。LLM 应只传：

- script_path
- solver
- working_dir
- mode
- timeout

具体命令由 executor 根据配置生成。

### 15.3 类接口

```python
class CAESimulatorExecutor:
    def __init__(self, workspace: Path, solver_profiles: dict[str, Any]):
        self.workspace = workspace
        self.solver_profiles = solver_profiles

    async def run(
        self,
        *,
        script_path: Path,
        solver: str,
        working_dir: Path,
        timeout_seconds: int,
        wait: bool = True,
    ) -> CAEJobResult:
        self._check_path(script_path)
        profile = self.solver_profiles[solver]
        command = self._build_command(profile, script_path)
        return await self._run_command(command, working_dir, timeout_seconds, wait)
```

### 15.4 solver profile

建议后续扩展配置：

```json
{
  "tools": {
    "cae": {
      "solvers": {
        "custom_cae": {
          "executable": "D:\\CAE\\custom_cae.exe",
          "scriptArg": "-script",
          "env": {},
          "timeoutSeconds": 7200
        }
      }
    }
  }
}
```

如果暂时不想改配置 schema，可先在 `executor.py` 中写 PoC profile，后续再抽配置。

### 15.5 Tool 封装

在 `tools.py` 中提供：

```python
class CAERunSimulationTool(Tool):
    @property
    def name(self) -> str:
        return "cae_run_simulation"

    @property
    def description(self) -> str:
        return "Run a validated CAE Python script using a configured CAE simulator."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script_path": {"type": "string"},
                "solver": {"type": "string"},
                "working_dir": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
                "wait": {"type": "boolean"},
            },
            "required": ["script_path", "solver", "working_dir"],
        }

    async def execute(self, **kwargs: Any) -> str:
        result = await self.executor.run(...)
        return result.model_dump_json()
```

### 15.6 测试建议

测试文件：

```text
tests/cae/test_executor.py
```

测试点：

- workspace 内脚本可执行。
- workspace 外脚本被拒绝。
- 超时返回 timeout。
- 非零 exit code 返回 failed。
- 日志路径被保存。

---

## 16. 后处理实现

### 16.1 新增文件

```text
nanobot/cae/postprocess.py
nanobot/cae/prompts/result_interpretation.md
```

### 16.2 职责

后处理模块负责：

- 读取仿真结果文件。
- 提取关键指标。
- 生成结构化结果。
- 生成报告摘要。

不要让 LLM 直接从任意日志中猜结论。

### 16.3 结构化结果

```python
class CAEResultMetric(BaseModel):
    name: str
    value: float | str
    unit: str | None = None
    location: str | None = None
    source_file: str | None = None

class CAEPostprocessResult(BaseModel):
    ok: bool
    metrics: list[CAEResultMetric] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    report_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

### 16.4 初期实现建议

MVP 不需要支持复杂结果文件格式。可以先支持：

- solver 输出 JSON。
- CSV。
- 简单日志。
- 你自定义的结果摘要文件。

后续再支持特定软件结果文件。

---

## 17. CAE Router 集成

### 17.1 新增文件

```text
nanobot/cae/router.py
```

### 17.2 职责

`CAERouter` 是 CAE 专用入口。它负责判断一条用户消息是否由 CAE 流程接管。

如果接管，返回 `OutboundMessage` 或内部响应；如果不接管，返回 `None`，让原 `AgentLoop` 继续处理。

### 17.3 类接口

```python
class CAERouter:
    def __init__(
        self,
        *,
        classifier: CAEIntentClassifier,
        skill_selector: CAESkillSelector,
        slot_filling: CAESlotFillingManager,
        planner: CAEPlanner,
        script_builder: CAEScriptBuilder,
        script_validator: CAEScriptValidator,
        executor: CAESimulatorExecutor,
        session_manager: SessionManager,
        workspace: Path,
        config: CAEConfig,
    ):
        ...

    async def handle(self, msg: InboundMessage, session: Session) -> OutboundMessage | None:
        existing = self._load_existing_state(session)
        if existing:
            return await self._continue_existing_task(msg, session, existing)

        intent = await self.classifier.classify(msg.content, session_context=session.get_history())
        if intent.top_level != "cae":
            return None

        return await self._start_cae_task(msg, session, intent)
```

### 17.4 接入 `AgentLoop._process_message`

修改：

```text
nanobot/agent/loop.py
```

建议接入位置：

1. 已经拿到 session。
2. 已经处理媒体文档抽取。
3. slash command 之前或之后均可，但建议 slash command 优先。
4. 原 `context.build_messages()` 之前。

伪代码：

```python
# Slash commands
raw = msg.content.strip()
ctx = CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)
if result := await self.commands.dispatch(ctx):
    return result

# CAE router
if self.cae_router is not None:
    cae_result = await self.cae_router.handle(msg, session)
    if cae_result is not None:
        self.sessions.save(session)
        return cae_result
```

### 17.5 初始化

在 `AgentLoop.__init__` 中：

```python
self.cae_router = None
if _tc.cae.enable:
    from nanobot.cae.router import build_cae_router
    self.cae_router = build_cae_router(
        provider=provider,
        model=self.model,
        workspace=workspace,
        session_manager=self.sessions,
        tool_registry=self.tools,
        cae_config=_tc.cae,
    )
```

注意初始化顺序：

- 先创建 `self.tools`。
- 注册默认工具。
- 注册 CAE 工具。
- 再构建 `CAESkillSelector`，因为它要检查 required tools。

---

## 18. CAE Tools 注册

### 18.1 新增文件

```text
nanobot/cae/tools.py
```

### 18.2 注册函数

```python
def register_cae_tools(
    registry: ToolRegistry,
    *,
    workspace: Path,
    cae_config: CAEConfig,
) -> CAEFunctionRegistry:
    cae_registry = CAEFunctionRegistry()

    # 1. 注册基础 CAE 函数
    register_builtin_cae_functions(cae_registry, workspace, cae_config)

    # 2. 转换为 nanobot Tool
    for spec in cae_registry.list_specs():
        registry.register(CAEFunctionTool(cae_registry, spec))

    # 3. 注册脚本构建、执行、后处理工具
    registry.register(CAEBuildScriptTool(...))
    registry.register(CAEValidateScriptTool(...))
    registry.register(CAERunSimulationTool(...))
    registry.register(CAEGetJobStatusTool(...))

    return cae_registry
```

### 18.3 MVP 工具清单

第一版建议只实现：

- `cae_import_geometry`
- `cae_assign_material`
- `cae_generate_mesh`
- `cae_apply_boundary_condition`
- `cae_apply_load`
- `cae_create_static_step`
- `cae_build_script`
- `cae_validate_script`
- `cae_run_simulation`
- `cae_extract_result`

### 18.4 工具返回要求

所有 CAE Tool 返回 JSON 字符串：

```json
{
  "ok": true,
  "function_name": "cae_generate_mesh",
  "script_fragment": "...",
  "data": {},
  "warnings": [],
  "errors": []
}
```

不要返回纯自然语言，避免后续脚本构建难以解析。

---

## 19. CAE Skill 编写规范

### 19.1 目录

```text
workspace/skills/standard-static-analysis/SKILL.md
```

### 19.2 标准模板

```markdown
---
description: Standard static structural analysis workflow.
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
        - cae_create_static_step
        - cae_build_script
        - cae_validate_script
        - cae_run_simulation
      required_inputs:
        - geometry
        - material
        - boundary_condition
        - load
        - mesh_size
        - solver
---

# Standard Static Analysis

Use this skill when the user asks to run a static structural analysis.

## Required Inputs

- geometry: CAD file path or geometry object.
- material: material name or elastic constants.
- boundary_condition: fixed support or displacement constraints.
- load: force, pressure, gravity, temperature, or other static loads.
- mesh_size: global mesh size or mesh strategy.
- solver: selected CAE software profile.

## Workflow

1. Import or create geometry.
2. Assign material.
3. Generate mesh.
4. Create static analysis step.
5. Apply boundary condition.
6. Apply load.
7. Build Python script.
8. Validate Python script.
9. Ask user for confirmation before execution.
10. Execute simulation.
11. Extract max stress, max displacement and safety factor.

## Rules

- Never guess material properties.
- Never guess load value or direction.
- Never execute before user confirmation.
- Always report script path, job id, log path and result directory.
```

### 19.3 编写原则

- Skill 写流程、规则和注意事项。
- Tool 执行具体动作。
- 参数 schema 写在 `CAEFunctionSpec` 中。
- 不要把大量可执行 Python 代码塞进 skill。
- 不要让 skill 绕过执行前确认。

---

## 20. 多轮对话流程

### 20.1 首轮参数不足

用户：

```text
帮我对这个支架做标准静力分析。
```

系统：

```text
我可以按“标准静力分析”流程处理。还需要确认以下参数：

1. 几何文件路径是什么？例如 D:\cases\bracket.step。
2. 材料参数是什么？例如钢，E=210GPa，nu=0.3。
3. 固定约束施加在哪个面/边/点？
4. 载荷大小、方向和施加位置是什么？
5. 全局网格尺寸是多少？例如 2 mm。
6. 使用哪个仿真软件配置？默认是 custom_cae。
```

内部状态：

```json
{
  "status": "collecting_params",
  "selected_skill": "standard-static-analysis",
  "missing_slots": ["geometry", "material", "boundary_condition", "load", "mesh_size", "solver"]
}
```

### 20.2 用户补充参数

用户：

```text
几何是 D:\case\bracket.step，材料钢 E=210GPa nu=0.3，左侧固定，右孔向下 1000N，网格 2mm，用 custom_cae。
```

系统：

```text
参数已完整。我将生成静力分析 Python 脚本。

参数摘要：
- 几何：D:\case\bracket.step
- 材料：钢，E=210 GPa，nu=0.3
- 约束：左侧固定
- 载荷：右孔向下 1000 N
- 网格：2 mm
- 求解器：custom_cae
```

然后系统生成脚本并校验。

### 20.3 执行前确认

系统：

```text
脚本已生成并通过校验。

脚本路径：D:\workspace\cae\scripts\task_xxx\run.py
结果目录：D:\workspace\cae\jobs\task_xxx

是否现在执行仿真？
```

用户：

```text
执行
```

系统调用 `cae_run_simulation`。

---

## 21. 实施阶段

### 21.1 第一阶段：低侵入 PoC

目标：跑通一个静力分析闭环。

改动：

- 新增 `workspace/skills/standard-static-analysis/SKILL.md`。
- 新增 `nanobot/cae/tools.py`。
- 新增 5 到 8 个基础 CAE Tool。
- 在 `AgentLoop._register_default_tools()` 中注册 CAE Tool。
- 通过提示词要求 Agent 按 skill 执行。

验收：

- 用户能触发标准静力分析 skill。
- 参数不足时会追问。
- 参数完整后能生成 Python 脚本。
- 能调用仿真软件执行脚本。

### 21.2 第二阶段：显式 Router 和状态机

目标：提升稳定性。

改动：

- 新增 `taxonomy.py`。
- 新增 `intent.py`。
- 新增 `skill_selector.py`。
- 新增 `slot_filling.py`。
- 新增 `router.py`。
- 将 `CAERouter` 接入 `AgentLoop._process_message()`。

验收：

- 闲聊不会误触发 CAE 流程。
- CAE 操作能进入参数状态机。
- 多轮参数补全可恢复。
- skill 能被显式选择。

### 21.3 第三阶段：函数注册和 Planner

目标：从工具堆叠升级为可维护函数体系。

改动：

- 新增 `registry.py`。
- 支持 manifest 加载。
- 新增 `planner.py`。
- 支持 skill workflow 到函数链映射。

验收：

- 新增 CAE 操作不需要修改核心 loop。
- planner 能生成确定性函数链。
- 缺少工具时能给出明确提示。

### 21.4 第四阶段：脚本治理和执行治理

目标：进入工程化使用。

改动：

- 新增 `script_builder.py`。
- 新增 `script_validator.py`。
- 新增 `executor.py`。
- 新增 job store。
- 新增日志和状态查询工具。

验收：

- 脚本可审计。
- 执行可追踪。
- 失败可诊断。
- 长任务可查询状态。

### 21.5 第五阶段：后处理和报告

目标：让 Agent 产出工程结论。

改动：

- 新增 `postprocess.py`。
- 新增结果提取工具。
- 新增报告生成工具。
- 接入结构化结果。

验收：

- 能提取最大应力、最大位移、安全系数。
- 能生成结果摘要。
- 报告中包含数据来源。

---

## 22. 测试计划

### 22.1 单元测试

必须覆盖：

- taxonomy 校验。
- 意图分类。
- skill metadata 解析。
- skill 选择。
- 函数注册。
- 参数补全。
- planner。
- script builder。
- script validator。
- executor。

### 22.2 集成测试

建议新增：

```text
tests/cae/test_static_analysis_flow.py
```

模拟流程：

1. 用户输入“帮我做静力分析”。
2. 系统追问参数。
3. 用户补充参数。
4. 系统生成脚本。
5. 用户确认执行。
6. executor 使用 fake solver 返回成功。
7. postprocess 返回结构化结果。

### 22.3 Fake Solver

为了测试，不要依赖真实 CAE 软件。建议新增 fake solver：

```text
tests/fixtures/fake_cae_solver.py
```

功能：

- 接收 Python 脚本路径。
- 写入 fake log。
- 写入 fake result JSON。
- 返回 exit code 0 或指定失败码。

### 22.4 回归测试

确保：

- CAE 功能关闭时，原 nanobot 行为不变。
- 闲聊不进入 CAE router。
- slash command 优先级不受影响。
- 现有工具注册顺序不受影响。

---

## 23. 安全要求

### 23.1 参数安全

- 不得猜测材料、载荷、边界条件。
- 缺失关键参数必须追问。
- 执行前必须展示参数摘要。

### 23.2 脚本安全

- 脚本必须生成在 workspace 下。
- 脚本必须经过语法检查。
- 禁止危险 import。
- 禁止任意 shell 命令。
- 禁止写 workspace 外路径。

### 23.3 执行安全

- 不允许 LLM 直接拼 shell 命令。
- executor 根据 solver profile 生成命令。
- 必须设置超时。
- 必须保存日志。
- 必须返回状态。

### 23.4 Skill 安全

- skill 只能定义流程和规则。
- skill 不能绕过用户确认。
- skill required_tools 必须存在。
- skill supported_solvers 必须匹配当前 solver。

---

## 24. 推荐开发顺序

建议按以下顺序提交 PR 或分支：

1. 新增 `nanobot/cae/schemas.py` 和 `taxonomy.py`。
2. 新增 CAE config。
3. 新增基础 CAE Tool 和注册入口。
4. 新增示例 skill `standard-static-analysis`。
5. 接入低侵入 PoC。
6. 新增 `CAEIntentClassifier`。
7. 新增 `CAESkillSelector`。
8. 新增 `CAESlotFillingManager`。
9. 新增 `CAERouter` 并接入 `AgentLoop`。
10. 新增 `CAEFunctionRegistry`。
11. 新增 `CAEPlanner`。
12. 新增 `CAEScriptBuilder` 和 `CAEScriptValidator`。
13. 新增 `CAESimulatorExecutor`。
14. 新增后处理。
15. 增加端到端测试。

---

## 25. MVP 验收标准

MVP 完成时，应能完成下面流程：

用户：

```text
帮我对支架做标准静力分析。
```

系统：

- 识别为 CAE 静力分析操作。
- 命中 `standard-static-analysis` skill。
- 发现参数不足并追问。

用户补充：

```text
几何 D:\case\bracket.step，材料钢 E=210GPa nu=0.3，左侧固定，右孔向下 1000N，网格 2mm，用 custom_cae。
```

系统：

- 抽取参数。
- 校验参数。
- 生成函数链。
- 生成 Python 脚本。
- 校验脚本。
- 询问是否执行。

用户：

```text
执行。
```

系统：

- 调用仿真软件执行接口。
- 返回 job_id、日志路径、结果目录。
- 如果 fake solver 或真实 solver 产出结果，则提取关键结果并返回摘要。

---

## 26. 最终架构原则

实现时应坚持以下原则：

- `nanobot` 原有 Agent runtime 不重写，只扩展。
- CAE 领域逻辑集中放在 `nanobot/cae/`。
- Skill 用来沉淀成熟流程和工程规则。
- Tool/MCP 用来执行确定性操作。
- Slot Filling 用来保证参数完整。
- Planner 用来保证流程顺序。
- Script Builder 用来生成可审计脚本。
- Executor 用来隔离仿真软件执行风险。
- PostProcessor 用结构化数据支撑工程结论。

最终目标是：

> 让 LLM 负责理解、规划和解释，让确定性代码负责参数校验、脚本生成、执行和结果提取。

