---
name: cae-functional-test
description: Minimal CAE workflow test for validating main-agent HITL and a two-round subagent HITL flow only.
always: true
---

# CAE Functional Test

只在用户明确要求以下任一事项时使用这个 skill：

- 运行 CAE 功能测试
- 测试 subagent HITL
- 提到 `cae-functional-test`

如果用户在做别的事情，忽略这个 skill。

## Hard Restrictions

- 这是 skill workflow 测试，不是代码库 `pytest` 测试。
- 不要运行 `pytest`。
- 不要扫描或修改 `tests/` 目录里的现有测试文件。
- 不要创建 CAD / Mesh / Physics / Sim-config 多阶段流程。
- 这个测试只允许使用一个子 skill：`subagent-hitl-test`。

## 测试目标

这个最小测试只验证三件事：

1. Main Agent 会不会先索取顶层必填输入
2. Main Agent 会不会启动 subagent
3. subagent 会不会连续两次发起阻断式 HITL，并在第二次补充后完成输出

## 顶层必填输入

启动 workflow 前，必须先拿到：

- `project_name`

`project_name` 只能来自用户在当前测试会话中的显式输入。

不要从下面这些来源推断、复用或猜测 `project_name`：

- 旧会话历史
- memory / summary
- 旧的 artifacts 目录名
- 旧的 workflow 文件名
- 之前测试里出现过的项目名
- 任何“从历史记录中已知”的假设

如果当前用户输入里没有明确给出 `project_name`，就一次性向用户追问，然后停止当前推进。
在 `project_name` 补齐前，不要启动 subagent。

## 输出目录

使用下面的目录结构：

`artifacts/subagent_hitl_test/<workflow_id>/`

只保留两个产物：

- `01_subagent_result.py`
- `final_test_result.py`

## Workflow ID

根据 `project_name` 生成稳定的 workflow id，例如：

`subagent-hitl-test-demo-project`

格式要求：

`subagent-hitl-test-<project-name-lowercase-with-hyphens>`

## 编排规则

每次处理这个 workflow 时，都按下面的逻辑：

1. 先确认当前用户是否已经显式提供 `project_name`
2. 如果没有提供，就先追问，不要继续
3. 只有在当前会话里已经拿到 `project_name` 后，才计算 `workflow_id`
4. 再检查 `artifacts/subagent_hitl_test/<workflow_id>/`
5. 如果缺少 `01_subagent_result.py`，启动 `subagent-hitl-test`
6. 否则如果缺少 `final_test_result.py`，写出最终汇总脚本
7. 否则告诉用户这个最小测试已经完成

一次只启动一个 subagent。

## Spawn 规则

启动 subagent 时必须：

- 传入 `workflow_id`
- 传入 `stage=subagent_hitl`
- 在任务文本里明确写出要读取并遵循 `subagent-hitl-test`
- 写明输出路径
- 写明当前已知的 `project_name`
- 明确要求它不要脑补默认值
- 明确要求它必须先追问第一组参数，再追问第二组参数
- 明确要求它不要把旧会话内容当成当前输入

参考任务结构：

```text
读取并遵循 skill `subagent-hitl-test`。

Workflow ID: subagent-hitl-test-demo-project
Stage: subagent_hitl
Output Path: artifacts/subagent_hitl_test/subagent-hitl-test-demo-project/01_subagent_result.py
Known Inputs:
- project_name: demo-project

Rules:
- Do not invent defaults.
- Ask for group 1 first.
- After group 1 is provided, ask for group 2.
- Return structured JSON if blocked.
```

## 子 Skill

只允许按需读取这个文件：

- `skills/subagent-hitl-test/SKILL.md`

## 最终汇总脚本

当 `01_subagent_result.py` 已经存在，且 `final_test_result.py` 还不存在时：

1. 写出 `final_test_result.py`
2. 脚本里定义 `run_final_test()`
3. `run_final_test()` 需要动态加载同目录下的 `01_subagent_result.py`
4. 调用 `run_subagent_hitl_stage()`
5. 返回一个简单的结果 dict，里面至少包含：
   - `status`
   - `workflow_id`
   - `stage_result`

脚本可以是假的，但结构要清楚，足够用于功能测试。

## 完成后的用户反馈

当两个文件都已经存在时，告诉用户：

- Main Agent HITL 已通过
- subagent 两轮 HITL 已通过
- 产物目录在哪里
