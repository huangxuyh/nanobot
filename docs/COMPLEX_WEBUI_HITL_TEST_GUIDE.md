# 复杂多子技能 HITL 测试指南

本文档对应当前实际运行目录中的技能：

- `C:\Users\yuanhao\.nanobot\workspace\skills\complex-hitl-workflow-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\requirement-hitl-stage`
- `C:\Users\yuanhao\.nanobot\workspace\skills\design-hitl-stage`
- `C:\Users\yuanhao\.nanobot\workspace\skills\execution-hitl-stage`
- `C:\Users\yuanhao\.nanobot\workspace\skills\review-hitl-stage`

旧技能：

- `cae-functional-test`
- `subagent-hitl-test`

已经被替换，不再作为当前测试入口使用。

---

## 1. 本次测试验证什么

这次不是最小链路测试，而是更复杂的顺序工作流测试：

1. 主技能先做顶层 HITL，获取 `project_name`
2. 主技能按顺序调用 4 个子技能
3. 每个子技能都做 2 轮阻断式 HITL
4. 每个子技能完成后写一个阶段 Python 文件
5. 4 个阶段都完成后，主技能写 `final_workflow.py`

总共会经历：

- 1 次主技能顶层 HITL
- 8 次子技能阻断式 HITL
- 5 个产物文件生成

---

## 2. 输出目录

假设你输入：

```text
project_name: demo-complex-webui
```

那么 workflow id 会是：

```text
complex-hitl-test-demo-complex-webui
```

输出目录会是：

```text
C:\Users\yuanhao\.nanobot\workspace\artifacts\complex_hitl_test\complex-hitl-test-demo-complex-webui\
```

最终应包含：

- `01_requirement_stage.py`
- `02_design_stage.py`
- `03_execution_stage.py`
- `04_review_stage.py`
- `final_workflow.py`

---

## 3. 推荐测试方式

建议你通过 WebUI 测试。

在 WebUI 中按顺序输入下面这些消息。

---

## 4. 测试案例

### 第 1 条输入

```text
请严格按 $complex-hitl-workflow-test 执行。这不是 pytest 测试。不要运行任何 tests/ 下的测试文件。禁止从记忆中读取任何参数。这是复杂多子技能 HITL 功能测试。
```

预期：

- 主技能不会直接启动子技能
- 会先追问：
  - `project_name`

### 第 2 条输入

```text
project_name: demo-complex-webui
```

预期：

- 主技能开始启动第一个子技能
- 第一个子技能进入第一轮 HITL
- 询问：
  - `requirement_name`
  - `requirement_scope`

### 第 3 条输入

```text
requirement_name: WebUI复杂工作流测试
requirement_scope: 验证4个子技能串行执行与阻断式HITL恢复
```

预期：

- 第一个子技能进入第二轮 HITL
- 询问：
  - `success_metric`
  - `delivery_deadline`

### 第 4 条输入

```text
success_metric: 生成4个阶段文件和1个最终汇总文件
delivery_deadline: 2026-05-01
```

预期：

- 生成 `01_requirement_stage.py`
- 自动进入第二个子技能
- 第二个子技能第一轮询问：
  - `design_style`
  - `module_count`

### 第 5 条输入

```text
design_style: 分层结构
module_count: 4
```

### 第 6 条输入

```text
primary_risk: 子技能恢复状态不一致
fallback_strategy: 主Agent检测文件并重新拉起当前阶段
```

预期：

- 生成 `02_design_stage.py`
- 自动进入第三个子技能

### 第 7 条输入

```text
execution_owner: yuanhao
execution_tool: webui
```

### 第 8 条输入

```text
execution_step_count: 8
execution_checkpoint: review-ready
```

预期：

- 生成 `03_execution_stage.py`
- 自动进入第四个子技能

### 第 9 条输入

```text
review_reviewer: test-reviewer
review_focus: 阻断式HITL与最终收尾
```

### 第 10 条输入

```text
release_decision: approve
followup_action: 进入WebUI回归测试
```

预期：

- 生成 `04_review_stage.py`
- 主技能生成 `final_workflow.py`
- 返回最终完成消息

---

## 5. 成功标志

### 前端成功标志

你应该看到：

1. 顶层先问 `project_name`
2. 然后 4 个子技能严格按顺序执行
3. 每个子技能都问两轮参数
4. 最后显示工作流完成

### 后端成功标志

日志里应该出现：

- 依次 `spawn` 4 个子技能阶段
- 每个阶段至少经历一次 `needs_user_input`
- 每个阶段最终写出自己的阶段文件
- 最后主技能写出 `final_workflow.py`

### 文件成功标志

最终目录下存在：

- `01_requirement_stage.py`
- `02_design_stage.py`
- `03_execution_stage.py`
- `04_review_stage.py`
- `final_workflow.py`

---

## 6. 如果你想重复测试

建议每次换一个新的 `project_name`，例如：

- `demo-complex-webui-a1`
- `demo-complex-webui-a2`
- `demo-complex-webui-a3`

这样可以避免旧 artifacts 干扰判断。

