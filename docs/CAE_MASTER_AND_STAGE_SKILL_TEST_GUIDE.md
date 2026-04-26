# CAE 主 Skill 与阶段 Skill 测试指南

本文档对应当前运行目录中的 CAE 功能测试 skill：

- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-master-flow-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-cad-stage-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-mesh-stage-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-physics-stage-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-preprocess-stage-test`
- `C:\Users\yuanhao\.nanobot\workspace\skills\cae-postprocess-stage-test`

这套 skill 的目标是测试：

1. 一个总 skill 顺序编排 5 个子 skill
2. 每个子 skill 的两轮阻断式 HITL
3. 从头完成一个完整 CAE 流程
4. 从已有脚本中间继续流程
5. 单独调用某一个阶段 skill

## 1. 本次 CAE 案例

建议使用同一个案例来测完整链路：

- 案例名称：`cantilever-demo`
- 几何：矩形悬臂梁
- 网格：四面体网格
- 物理场：线性静力
- 前处理：单位与求解器配置
- 后处理：应力云图与结果导出

## 2. 输出目录

如果输入：

```text
project_name: cantilever-demo
```

则 workflow id 为：

```text
cae-flow-test-cantilever-demo
```

输出目录：

```text
C:\Users\yuanhao\.nanobot\workspace\artifacts\cae_flow_test\cae-flow-test-cantilever-demo\
```

完整流程最终应包含：

- `01_cad_stage.py`
- `02_mesh_stage.py`
- `03_physics_stage.py`
- `04_preprocess_stage.py`
- `05_postprocess_stage.py`
- `final_cae_workflow.py`

## 3. 本地样例脚本

已提供 3 个本地 `.py` 文件，用于测试“从中间继续”与“单独调用某阶段”：

- [C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_done_only.py](C:/Users/yuanhao/.nanobot/workspace/cae_test_inputs/cad_done_only.py)
- [C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_mesh_done.py](C:/Users/yuanhao/.nanobot/workspace/cae_test_inputs/cad_mesh_done.py)
- [C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_mesh_physics_done.py](C:/Users/yuanhao/.nanobot/workspace/cae_test_inputs/cad_mesh_physics_done.py)

这些文件都包含：

```python
COMPLETED_STAGES = [...]
```

主 skill 会优先读取它来判断哪些上游阶段已经完成。

## 4. 测试案例 A：从头完成完整流程

### 输入 1

```text
请严格按 $cae-master-flow-test 执行。这不是 pytest 测试。不要运行任何 tests/ 下的测试文件。禁止从记忆中读取任何参数。我需要从头完成一个完整的 CAE 功能测试流程。
```

预期：

- 主 skill 先追问 `project_name`

### 输入 2

```text
project_name: cantilever-demo-a1
```

### CAD 两轮输入

```text
cad_model_name: cantilever-beam
cad_geometry_summary: 一端固定一端自由的矩形悬臂梁
```

```text
cad_material_hint: steel
cad_export_format: step
```

### Mesh 两轮输入

```text
mesh_method: tetra
mesh_size: 2.0 mm
```

```text
mesh_quality_target: medium
mesh_element_order: first-order
```

### Physics 两轮输入

```text
physics_domain: linear-static
load_summary: free end downward load
```

```text
boundary_summary: left face fixed
solve_goal: displacement and stress check
```

### Preprocess 两轮输入

```text
preprocess_script_name: setup_case_a
unit_system: mm-N-s
```

```text
validation_rule: check-missing-fields
solver_preset: static-default
```

### Postprocess 两轮输入

```text
report_name: cantilever_report
output_metric: max_stress
```

```text
plot_type: contour
export_format: png
```

成功标志：

- 5 个阶段依次执行
- 每个阶段都发生 2 轮 HITL
- 最终生成全部 6 个脚本

## 5. 测试案例 B：已有 CAD + Mesh，只跑后 3 个阶段

### 输入 1

```text
请严格按 $cae-master-flow-test 执行。我已经有前面流程脚本，只需要从后面继续。
```

### 输入 2

```text
project_name: partial-demo-b1
script_path: C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_mesh_done.py
```

预期：

- 主 skill 读取 `cad_mesh_done.py`
- 识别：

```python
COMPLETED_STAGES = ["cad", "mesh"]
```

- 跳过 `cad` 和 `mesh`
- 只执行：
  - `physics`
  - `preprocess`
  - `postprocess`

## 6. 测试案例 C：单独调用 Mesh skill

### 输入 1

```text
请使用 $cae-mesh-stage-test。我已经有 CAD 脚本，只需要网格阶段功能测试。
```

### 输入 2

```text
project_name: mesh-only-demo-c1
script_path: C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_done_only.py
```

### 输入 3

```text
mesh_method: quad-dominant
mesh_size: 1.0 mm
```

### 输入 4

```text
mesh_quality_target: high
mesh_element_order: second-order
```

预期：

- 只执行 Mesh 阶段
- 不会再跑 Physics / Preprocess / Postprocess
- 生成 `02_mesh_stage.py`

## 7. 测试案例 D：已有 CAD + Mesh + Physics，只跑后 2 个阶段

### 输入

```text
请严格按 $cae-master-flow-test 执行。我提供一个已有三阶段脚本，请从 preprocess 继续。
project_name: preprocess-demo-d1
script_path: C:\Users\yuanhao\.nanobot\workspace\cae_test_inputs\cad_mesh_physics_done.py
```

预期：

- 跳过：
  - `cad`
  - `mesh`
  - `physics`
- 只执行：
  - `preprocess`
  - `postprocess`

## 8. 成功判定

### 主 skill 成功

- 先追问 `project_name`
- 能根据 `script_path` 判断跳过哪些阶段
- 严格按顺序调用子 skill

### 子 skill 成功

- 每个阶段都出现 2 轮 HITL
- 每个阶段完成后都写出对应阶段脚本

### 产物成功

完整流程最终应有：

- `01_cad_stage.py`
- `02_mesh_stage.py`
- `03_physics_stage.py`
- `04_preprocess_stage.py`
- `05_postprocess_stage.py`
- `final_cae_workflow.py`

## 9. 使用建议

- 每次测试尽量换新的 `project_name`
- 如果要验证“忽略已有产物重新测试”，再显式加一句：

```text
请忽略已有产物重新测试
```

- 替换了 skill 后请重启 `nanobot gateway`

