# 最小化 Subagent HITL 测试指南

本文档说明如何测试当前仓库里的最小 skill 测试链路。

这次测试只保留两个 skill：

- `cae-functional-test`
- `subagent-hitl-test`

不再使用这些旧 skill：

- `cad-functional-test`
- `mesh-functional-test`
- `physics-functional-test`
- `sim-config-functional-test`

## 1. 这个测试验证什么

它只验证三件事：

1. Main Agent 顶层 HITL
2. Main Agent 启动 subagent
3. subagent 连续两次阻断并恢复

它不验证真实 CAE 算法，也不验证真实 CAD、网格、物理场或求解器。

## 2. 运行前检查

如果你的实际运行目录不是当前仓库，而是单独的 workspace `skills/` 目录，那么需要先同步这两个 skill：

- `skills/cae-functional-test/SKILL.md`
- `skills/subagent-hitl-test/SKILL.md`

同时删除旧的 4 个测试 skill，避免继续误触发旧流程。

## 3. 启动方式

在正确的 Python / conda 环境里启动：

```powershell
nanobot agent --logs
```

为了避免旧上下文干扰，建议每次测试前先输入：

```text
/new
```

## 4. 推荐测试输入

第一轮输入：

```text
请严格按 $cae-functional-test 执行。
这不是 pytest 测试。
不要运行任何 tests/ 下的测试文件。
```

### 第一轮成功现象

如果成功，Main Agent 不应该启动 subagent。

它应该先追问：

- `project_name`

这说明顶层 HITL 成功。

## 5. 第二轮输入

当 Agent 追问 `project_name` 后，输入：

```text
project_name: demo-hitl
```

### 第二轮成功现象

如果成功，你应该看到：

- Agent 不再追问顶层字段
- 日志里出现 `spawn(...)`
- 启动的目标是 `subagent-hitl-test`

这说明 Main Agent 已经开始调用 subagent。

## 6. 第三轮输入

当 subagent 发起第一次阻断后，输入：

```text
group1_name: first-check
group1_value: alpha
```

### 第三轮成功现象

如果成功，你应该看到：

- Agent 明确说第一组已收到
- 然后继续追问第二组参数
- 这时还不应该宣布整个测试完成
- `01_subagent_result.py` 此时通常还没有最终完成，或者即使文件已准备，也不应结束整个 workflow

这说明第一次 subagent HITL 成功恢复。

## 7. 第四轮输入

当 Agent 追问第二组参数后，输入：

```text
group2_name: second-check
group2_value: beta
```

### 第四轮成功现象

如果成功，你应该看到：

- subagent 不再继续追问
- `01_subagent_result.py` 被写出
- 主流程继续完成 `final_test_result.py`
- 最终返回“测试完成”之类的消息

## 8. 最终产物

成功后，目录下应至少有两个文件：

`artifacts/subagent_hitl_test/subagent-hitl-test-demo-hitl/`

其中包括：

- `01_subagent_result.py`
- `final_test_result.py`

## 9. 什么才算真正通过

下面四点同时满足，才算这次最小测试通过：

1. 首轮只追问 `project_name`
2. 补完 `project_name` 后出现 `spawn(...)`
3. subagent 先问第一组，再问第二组
4. 第二组补完后才真正完成并写出两个产物文件

## 10. 哪些现象说明失败了

下面任一情况都说明测试没有按预期工作：

- 一开始就去运行 `pytest`
- 一开始就扫描 `tests/`
- 没有 `spawn(...)`
- subagent 一次性把两组参数全问完
- subagent 自己脑补默认值
- 只补第一组参数就直接完成
- 第二轮恢复时又从头开始追问第一组

## 11. 建议查看的日志信号

成功时，日志里通常会出现这些信号：

- `read_file(...skills\\cae-functional-test\\SKILL.md)`
- `spawn(...)`
- `Subagent [...] starting task`
- `needs_user_input`
- 第二次恢复后写出 `01_subagent_result.py`
- 最后写出 `final_test_result.py`

## 12. 这次日志问题怎么判断

如果你看到主 skill 直接说“从历史记录中已知 project_name = ...”，那就不算通过。

正确行为应该是：

- 当前轮用户没有显式提供 `project_name`
- Main Agent 就必须先追问 `project_name`
- 追问之前不能启动 subagent

如果你看到 subagent 提示：

- `group1_name`
- `group1_value`

那说明第一轮 subagent HITL 已经触发了。

不要把它和主 skill 的顶层 HITL 混在一起。

## 13. 清理方式

如果要重新测同一个 `project_name`，建议先删掉对应产物目录和 workflow 文件。

重点清理：

- `artifacts/subagent_hitl_test/subagent-hitl-test-demo-hitl/`
- 对应的 `workflows/<workflow_id>.json`

如果你想最干净地重新开始，也可以直接：

1. 删掉对应产物
2. 输入 `/new`
3. 重新按本文档 4 到 7 节测试
