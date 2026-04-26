# CAE Functional Test Guide

本文档说明如何测试当前仓库中新增的 CAE 功能测试 workflow。

测试资产包括：

- `skills/` 下的 workspace skills
- `tests/manual/CAE_FUNCTIONAL_TEST_CASES.md` 里的手工测试输入案例

## 1. 这个测试覆盖什么

这只是功能验证，不是业务正确性验证。

它验证的是：

1. subagent 编排前的 Main-Agent HITL
2. 阶段顺序执行
3. 由 subagent 发起的阻断式 HITL
4. 用户补充信息后的恢复执行
5. 最终 Python 文件拼装

它不验证真实 CAD、网格、物理场和求解器的正确性。

## 2. 新增的 Skills

本次测试使用这些 workspace skills：

- `cae-functional-test`
- `cad-functional-test`
- `mesh-functional-test`
- `physics-functional-test`
- `sim-config-functional-test`

为了方便测试，`cae-functional-test` 被标记成了 `always: true`，但它内部有保护条件：

- 只有当用户明确要求运行 CAE 功能测试时，它才应该真正生效

## 3. 预期输出位置

测试成功时，workflow 应该把文件写到：

`artifacts/cae_functional_test/<workflow_id>/`

预期文件：

- `01_cad_stage.py`
- `02_mesh_stage.py`
- `03_physics_stage.py`
- `04_sim_config_stage.py`
- `final_cae_workflow.py`

## 4. 推荐测试顺序

建议按这个顺序测试：

1. 用例 1：Main-Agent HITL
2. 用例 2：无额外阶段 HITL 的顺序编排
3. 用例 3：Mesh 阶段 subagent HITL 与恢复

手工测试输入案例在：

[CAE_FUNCTIONAL_TEST_CASES.md](D:/code/nanobot/nanobot/tests/manual/CAE_FUNCTIONAL_TEST_CASES.md)

## 5. 如何启动并输入测试

你需要通过 `nanobot agent` 启动交互式 Agent，然后在交互界面里逐条输入测试案例。

典型流程是：

1. 在终端进入仓库目录
2. 启动 `nanobot agent`
3. 看到交互输入提示后，直接粘贴测试案例里的文本
4. 按案例要求继续补充第二轮输入
5. 观察 agent 的追问、subagent 顺序、文件输出和 workflow 恢复行为

如果你的环境已经配置好，可以直接使用：

```powershell
nanobot agent
```

如果你是通过虚拟环境运行，就先激活虚拟环境再执行上面的命令。

## 6. 用例 1：Main-Agent HITL

目的：

- 验证顶层 CAE skill 会在启动任何 subagent 前，先向用户索取缺失的必填输入

预期行为：

1. 你先发送一条信息不完整的请求
2. Main Agent 追问缺失的顶层信息
3. 此时还不应该生成任何阶段文件
4. 当你补充完信息后，CAD 阶段才开始执行

通过标准：

- agent 确实追问了缺失字段
- 在顶层必填字段补齐前，不会启动 mesh/physics/sim-config

## 7. 用例 2：顺序编排

目的：

- 验证阶段按顺序执行

预期行为：

1. CAD 阶段写出 `01_cad_stage.py`
2. mesh 阶段写出 `02_mesh_stage.py`
3. physics 阶段写出 `03_physics_stage.py`
4. sim-config 阶段写出 `04_sim_config_stage.py`
5. 最终拼装写出 `final_cae_workflow.py`

通过标准：

- 阶段文件按顺序出现
- 最终脚本被写出
- 最终脚本包含名为 `run_cae_functional_test()` 的包装函数

## 8. 用例 3：Mesh Subagent HITL

目的：

- 验证新的阻断式 subagent HITL 路径

预期行为：

1. 因为项目级输入已经足够，顶层 workflow 会开始执行
2. CAD 阶段完成
3. mesh subagent 发现缺少 `mesh_size` 和 `mesh_method`
4. mesh subagent 返回结构化 JSON
5. Main Agent 向你追问缺失的 mesh 输入
6. 当前 workflow 进入暂停等待
7. 当你回复后，workflow 从 mesh 阶段恢复，而不是从 CAD 重新开始

通过标准：

- 你能看到 mesh 阶段的专门追问
- 回复后，agent 恢复当前 workflow
- 不会从 CAD 重新开始
- 后续阶段会继续执行直至完成

## 9. 测试时需要检查哪些文件

每轮测试后，建议检查：

- `artifacts/cae_functional_test/`
- `workflows/`
- `sessions/`

重点看：

- workflow 产物目录下的阶段脚本
- `workflows/` 下的 workflow JSON
- `sessions/` 下的当前会话状态

对于 subagent HITL 用例，workflow JSON 理论上会临时经历这些状态：

- `awaiting_user_input`
- `resuming`
- `running`

## 10. 当前已知限制

这是一套功能测试脚手架，所以以下限制是有意保留的：

- 阶段脚本都是假的 Python 代码
- CAE 逻辑是假的
- 顺序编排是由顶层 skill 软控制的
- workflow id 是约定生成，不是专门工具生成

这些限制对当前功能测试是可以接受的。

## 11. 如果测试失败，先查什么

如果 workflow 行为不符合预期，建议按这个顺序排查：

1. 检查用户输入是否明确要求运行 CAE 功能测试
2. 检查 Main Agent 是否确实加载了 `cae-functional-test`
3. 检查被启动的 subagent 是否读取了对应阶段的 skill
4. 检查 `workflows/` 下是否写出了 workflow JSON
5. 检查被阻断的阶段是否返回了结构化 JSON，而不是自由文本

## 12. 清理方式

如果你想在两次测试之间重置状态，可以删除对应 workflow 的生成目录：

- `artifacts/cae_functional_test/<workflow_id>/`
- `workflows/<workflow_id>.json`

如果你希望手工测试更干净，也可以重新开启一个新的会话。
