# Windows 本地启动 WebUI 测试指南

本文档基于当前仓库实际结构编写，目标是帮助你在 Windows 本地启动：

- nanobot 后端运行时
- WebSocket / WebUI 所需服务
- WebUI 前端开发服务器

并明确说明：

- WebUI 应该连接哪个后端
- `nanobot gateway` 和 `nanobot serve` 的区别
- 后续如何用 WebUI 测试你现在的 subagent blocking HITL 流程

---

## 1. 先说结论

如果你要测试当前仓库里的 `webui/`，**应该启动的是 `nanobot gateway`，不是 `nanobot serve`**。

原因是：

- `webui/` 通过 `webui/bootstrap`、`/api/sessions`、`/api/media` 和 WebSocket 连接工作
- 这些能力是由 **WebSocket channel** 提供的
- `nanobot serve` 只提供 OpenAI-compatible API：
  - `/v1/chat/completions`
  - `/v1/models`
  - `/health`
- `nanobot serve` 不是当前 WebUI 的后端

所以你本地测试 WebUI 时，正确组合是：

1. 启动 `nanobot gateway`
2. 启动 `webui` 的 Vite dev server
3. 浏览器打开 `http://127.0.0.1:5173`

---

## 2. 当前项目里的相关端口

当前仓库默认有两组端口：

- Gateway 健康检查端口：`127.0.0.1:18790`
- WebSocket channel / WebUI REST / 静态页端口：`127.0.0.1:8765`
- WebUI dev server：`127.0.0.1:5173`
- Vite HMR：`127.0.0.1:5174`
- OpenAI-compatible API：`127.0.0.1:8900`

注意：

- 你在浏览器里开发时实际打开的是 `5173`
- 但 `5173` 会把 `/api`、`/webui`、`/auth` 和 WebSocket 转发到 `8765`
- 所以真正给 WebUI 提供数据的是 **WebSocket channel**

---

## 3. 启动前准备

### 3.1 Python 环境

建议至少满足：

- Python `3.11+`

你当前本地如果仍然是 3.9，CLI 可能能部分运行，但完整测试和依赖兼容性不稳。  
如果只是先跑通 WebUI，也尽量切到项目推荐版本。

### 3.2 安装 Python 依赖

在仓库根目录：

```powershell
cd D:\code\nanobot\nanobot
pip install -e .
```

如果你已经在当前环境里安装过，可跳过。

### 3.3 Node / npm

`webui/` 是 Vite + React 项目，需要 Node.js。

建议：

- Node.js `18+`
- `npm` 可用

检查：

```powershell
node -v
npm -v
```

---

## 4. 配置 WebSocket channel

WebUI 依赖 WebSocket channel，所以 `~/.nanobot/config.json` 里必须启用它。

最小示例：

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765,
      "path": "/",
      "websocketRequiresToken": false,
      "allowFrom": ["*"],
      "streaming": true
    }
  }
}
```

如果你已经有自己的 `config.json`，只需要把 `channels.websocket` 这一段合进去，不要整份覆盖。

### 为什么这里建议 `websocketRequiresToken: false`

因为你现在是本地单机开发测试。

这样可以减少本地调试复杂度。  
后面如果你要做外网部署，再恢复安全配置。

---

## 5. 启动后端

### 5.1 启动 nanobot gateway

打开终端 1：

```powershell
cd D:\code\nanobot\nanobot
conda activate nanobot
nanobot gateway
```

如果你想看更详细日志：

```powershell
nanobot gateway --verbose
```

### 5.2 启动成功后你应该看到什么

至少应该看到类似信息：

```text
Starting nanobot gateway ...
Channels enabled: websocket
Health endpoint: http://127.0.0.1:18790/health
WebSocket server listening on ws://127.0.0.1:8765/
```

如果没有看到 `8765` 的 WebSocket server 监听信息，说明 WebSocket channel 没真的启动成功，WebUI 也就连不上。

---

## 6. 启动前端

打开终端 2：

```powershell
cd D:\code\nanobot\nanobot\webui
npm install
npm run dev
```

如果你习惯 `bun`，也可以：

```powershell
bun install
bun run dev
```

### 6.1 成功后你应该看到什么

类似：

```text
VITE v...
Local: http://127.0.0.1:5173/
```

然后浏览器打开：

```text
http://127.0.0.1:5173
```

---

## 7. WebUI 的连接关系

开发模式下，WebUI 不是直接自己工作，它会这样转发：

```text
浏览器 -> 5173(Vite)
      -> 8765(WebSocket channel)
```

也就是：

- `/webui/bootstrap` -> `8765`
- `/api/sessions` -> `8765`
- `/auth/...` -> `8765`
- WebSocket upgrade -> `8765`

所以测试 WebUI 时，你最该关心的是：

- 终端 1 的 `nanobot gateway` 日志
- 8765 是否活着

而不是 `nanobot serve`

---

## 8. 可选：构建后直接由后端静态托管

如果你不想跑 `vite dev server`，也可以先 build，再让 WebSocket channel 直接托管打包产物。

### 8.1 构建前端

在终端 2：

```powershell
cd D:\code\nanobot\nanobot\webui
npm install
npm run build
```

这会把产物写到：

- `D:\code\nanobot\nanobot\nanobot\web\dist`

### 8.2 再启动 gateway

```powershell
cd D:\code\nanobot\nanobot
conda activate nanobot
nanobot gateway
```

构建产物存在时，WebSocket channel 会把静态页面一起托管出去。  
这种情况下，通常可以直接访问 `8765` 对应地址进行测试。

但你现在是开发和功能验证阶段，**更建议先用 `5173` dev server**，排错更方便。

---

## 9. `nanobot gateway` 和 `nanobot serve` 的区别

### `nanobot gateway`

用途：

- 启动 AgentLoop
- 启动已启用的 channels
- 启动 WebSocket channel
- 给 WebUI 提供：
  - `/webui/bootstrap`
  - `/api/sessions`
  - `/api/media`
  - WebSocket 实时聊天

你测试 WebUI 时必须启动它。

### `nanobot serve`

用途：

- 启动 OpenAI-compatible HTTP API
- 提供：
  - `/v1/chat/completions`
  - `/v1/models`
  - `/health`

它适合：

- 让外部程序按 OpenAI 接口调用 nanobot
- 用脚本或第三方工具调 `/v1/chat/completions`

它**不是当前 WebUI 的后端**。

---

## 10. 用 WebUI 测你当前的 HITL 功能

### 10.1 建议测试前清理旧产物

如果你反复用同一个 `project_name`，建议先删：

```text
C:\Users\yuanhao\.nanobot\workspace\artifacts\subagent_hitl_test\subagent-hitl-test-demo-hitl
```

以及如果存在：

```text
C:\Users\yuanhao\.nanobot\workspace\workflows\subagent-hitl-test-demo-hitl.json
```

### 10.2 在 WebUI 里按这个顺序输入

第一轮：

```text
请严格按 $cae-functional-test 执行。这不是 pytest 测试。不要运行任何 tests/ 下的测试文件。禁止从记忆中读取任何的参数。请忽略已有产物重新测试
```

预期：

- WebUI 中先收到主 Agent 的顶层 HITL
- 它会问你 `project_name`

第二轮：

```text
project_name: demo-hitl
```

预期：

- 启动 subagent
- 然后正式请求第一组参数

第三轮：

```text
group1_name: first-check;group1_value: alpha
```

预期：

- 第一轮 subagent HITL 结束
- 进入第二轮参数请求

第四轮：

```text
group2_name: second-check;group2_value: beta
```

预期：

- 生成 `01_subagent_result.py`
- 生成 `final_test_result.py`
- WebUI 最终出现完成消息

---

## 11. 你应该看到什么才算成功

### 前端现象

WebUI 里应该能看到：

- 主 Agent 先追问 `project_name`
- 再看到第一轮参数请求
- 再看到第二轮参数请求
- 最终看到完成消息

### 后端日志现象

终端 1 应该能看到：

- `Spawned subagent [...]`
- `Processing system message from subagent`
- 第二轮恢复后写出：
  - `01_subagent_result.py`
  - `final_test_result.py`

### 最终产物

应出现在：

- `C:\Users\yuanhao\.nanobot\workspace\artifacts\subagent_hitl_test\subagent-hitl-test-demo-hitl\01_subagent_result.py`
- `C:\Users\yuanhao\.nanobot\workspace\artifacts\subagent_hitl_test\subagent-hitl-test-demo-hitl\final_test_result.py`

---

## 12. 常见问题

### 12.1 打开 5173 后页面报连接失败

优先检查：

1. `nanobot gateway` 是否正在运行
2. `channels.websocket.enabled` 是否为 `true`
3. 8765 端口是否成功监听

### 12.2 起了 `nanobot serve` 但 WebUI 还是不通

这是正常的，因为 `serve` 不是 WebUI 后端。  
请改为启动：

```powershell
nanobot gateway
```

### 12.3 WebUI 能打开，但聊天列表 / 会话加载失败

优先检查：

- `webui/bootstrap`
- `/api/sessions`

这两个接口都来自 `8765` 的 WebSocket channel。

### 12.4 Vite 启动了，但还是连错后端

可以显式指定 dev server 代理目标：

```powershell
cd D:\code\nanobot\nanobot\webui
$env:NANOBOT_API_URL="http://127.0.0.1:8765"
npm run dev
```

---

## 13. 推荐的本地测试方式

当前阶段建议你用下面这套：

终端 1：

```powershell
cd D:\code\nanobot\nanobot
conda activate nanobot
nanobot gateway --verbose
```

终端 2：

```powershell
cd D:\code\nanobot\nanobot\webui
npm install
npm run dev
```

浏览器：

```text
http://127.0.0.1:5173
```

这是最适合你现在做 WebUI + subagent HITL 联调的方式。

