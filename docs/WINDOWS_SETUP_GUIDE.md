# Windows 安装与运行指南

> 适用于 Windows 10/11，Python 3.11+

---

## 一、环境准备

### 1.1 安装 Python

Nanobot 要求 Python 3.11 或更高版本。

1. 前往 [Python 官网](https://www.python.org/downloads/) 下载最新版 Python（3.11/3.12/3.13/3.14 均可）
2. 安装时**务必勾选** "Add Python to PATH"
3. 安装完成后打开命令行验证：

```bash
python --version
# 应显示 Python 3.11.x 或更高版本
```

### 1.2 安装 Git（可选，源码安装时需要）

前往 [Git for Windows](https://git-scm.com/download/win) 下载并安装。

### 1.3 安装 Node.js（可选，使用 WhatsApp 频道时需要）

如果使用 WhatsApp 频道，需要 Node.js ≥ 18。前往 [Node.js 官网](https://nodejs.org/) 下载 LTS 版本。

---

## 二、安装 Nanobot

有两种安装方式，任选其一。

### 方式 A：通过 pip 安装（推荐新手）

```bash
pip install nanobot-ai
```

安装完成后验证：

```bash
nanobot --version
```

### 方式 B：从源码安装（推荐开发者）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

> `-e` 表示可编辑模式，修改代码后即时生效。

### 可选依赖

某些频道和功能需要额外依赖，按需安装：

```bash
# 微信频道
pip install "nanobot-ai[weixin]"

# 企业微信频道
pip install "nanobot-ai[wecom]"

# MS Teams 频道
pip install "nanobot-ai[msteams]"

# Discord 频道
pip install "nanobot-ai[discord]"

# API Server（HTTP 服务）
pip install "nanobot-ai[api]"

# 开发依赖（测试、lint）
pip install "nanobot-ai[dev]"
```

> **注意**：Matrix 频道**不支持 Windows**（依赖 `python-olm`，无 Windows 预编译包）。如需使用请借助 WSL2。

---

## 三、初始化配置

### 3.1 运行 onboarding

```bash
nanobot onboard
```

这会在 `~/.nanobot/` 目录下创建配置文件和 workspace。在 Windows 上，`~` 通常对应 `C:\Users\你的用户名\`。

如果想使用交互式向导：

```bash
nanobot onboard --wizard
```

### 3.2 编辑配置文件

配置文件位于 `C:\Users\你的用户名\.nanobot\config.json`。

**最少只需配置两项：API Key + 模型。**

以 OpenRouter 为例：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-6",
      "provider": "openrouter"
    }
  }
}
```

> 推荐使用 [OpenRouter](https://openrouter.ai/keys)（一个 Key 可访问多个模型）。
> 其他提供商（Anthropic 直连、OpenAI、智谱、通义千问、DeepSeek、Ollama 本地等）请参考 README 的 Providers 部分。

### 3.3 设置时区（推荐）

```json
{
  "agents": {
    "defaults": {
      "timezone": "Asia/Shanghai"
    }
  }
}
```

---

## 四、开始使用

### 4.1 CLI 交互模式

最简单的使用方式：

```bash
nanobot agent
```

进入交互后直接输入问题即可。退出方式：`exit`、`quit`、`/exit`、`:q` 或 `Ctrl+D`。

### 4.2 单次问答

```bash
nanobot agent -m "你好，请介绍一下自己"
```

### 4.3 Gateway 模式（接入聊天平台）

如果要连接 Telegram、Discord、飞书等聊天平台：

```bash
nanobot gateway
```

Gateway 会持续运行，监听各频道的消息。

### 4.4 API Server 模式

```bash
pip install "nanobot-ai[api]"
nanobot serve
```

默认绑定 `127.0.0.1:8900`，提供 OpenAI 兼容的 API：

```bash
curl http://127.0.0.1:8900/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}]}"
```

> Windows CMD 中使用 `^` 换行，PowerShell 中使用 `` ` `` 换行。

---

## 五、接入聊天平台

以下以几个常用平台为例：

### 5.1 Telegram（推荐）

1. 在 Telegram 中搜索 `@BotFather`，发送 `/newbot` 创建机器人，复制返回的 token
2. 在 Telegram 设置中找到你的 User ID（格式为 `@yourUserId`，去掉 `@`）
3. 编辑 `config.json`：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

4. 启动 Gateway：

```bash
nanobot gateway
```

### 5.2 飞书（Feishu）

1. 前往 [飞书开放平台](https://open.feishu.cn/app) 创建应用，启用机器人能力
2. 添加权限：`im:message`、`im:message.p2p_msg:readonly`，流式回复还需 `cardkit:card:write`
3. 添加事件订阅：`im.message.receive_v1`，选择**长连接**模式
4. 获取 App ID 和 App Secret
5. 编辑 `config.json`：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "allowFrom": ["ou_YOUR_OPEN_ID"],
      "groupPolicy": "mention",
      "streaming": true,
      "domain": "feishu"
    }
  }
}
```

6. 发布应用后启动 Gateway：

```bash
nanobot gateway
```

### 5.3 钉钉（DingTalk）

1. 前往 [钉钉开放平台](https://open-dev.dingtalk.com/) 创建应用，添加机器人能力
2. 开启** Stream 模式**
3. 获取 AppKey 和 AppSecret
4. 编辑 `config.json`：

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

5. 发布应用后启动 Gateway：

```bash
nanobot gateway
```

### 5.4 微信（Weixin）

```bash
# 安装微信依赖
pip install "nanobot-ai[weixin]"

# 扫码登录
nanobot channels login weixin
```

配置：

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allowFrom": ["YOUR_WECHAT_USER_ID"]
    }
  }
}
```

启动 Gateway：

```bash
nanobot gateway
```

### 5.5 WhatsApp

> 需要 Node.js ≥ 18

```bash
# 终端 1：扫码登录
nanobot channels login whatsapp

# 终端 2：启动 Gateway
nanobot gateway
```

配置：

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

---

## 六、使用环境变量存储密钥

不想把 API Key 明文放在配置文件中？可以使用环境变量：

### 6.1 设置环境变量

在 Windows PowerShell 中：

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-xxx"
$env:TELEGRAM_TOKEN = "your-bot-token"
```

或者在系统环境变量中永久设置：
1. 右键"此电脑" → "属性" → "高级系统设置" → "环境变量"
2. 添加新的用户/系统变量

### 6.2 在配置中引用

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "channels": {
    "telegram": {
      "token": "${TELEGRAM_TOKEN}"
    }
  }
}
```

---

## 七、常用命令速查

| 命令 | 说明 |
|------|------|
| `nanobot onboard` | 初始化配置和 workspace |
| `nanobot onboard --wizard` | 交互式设置向导 |
| `nanobot agent` | CLI 交互聊天 |
| `nanobot agent -m "问题"` | 单次问答 |
| `nanobot gateway` | 启动 Gateway（接入聊天平台） |
| `nanobot serve` | 启动 OpenAI 兼容 API |
| `nanobot status` | 查看状态 |
| `nanobot --version` | 查看版本 |

### 升级

```bash
pip install -U nanobot-ai
nanobot --version
```

---

## 八、聊天内命令

在任意聊天频道或 CLI 会话中可用：

| 命令 | 说明 |
|------|------|
| `/new` | 开始新对话 |
| `/stop` | 停止当前任务 |
| `/restart` | 重启机器人 |
| `/status` | 查看状态 |
| `/dream` | 手动触发 Dream 记忆整合 |
| `/dream-log` | 查看最近的记忆变更 |
| `/help` | 查看可用命令 |

---

## 九、常见问题

### 9.1 `nanobot` 命令找不到

确保 Python 已正确添加到 PATH。重新打开命令行窗口后再试。可以显式调用：

```bash
python -m nanobot.cli.commands agent
```

### 9.2 配置文件中路径使用

Windows 路径在 JSON 中使用正斜杠或双反斜杠：

```json
{
  "agents": {
    "defaults": {
      "workspace": "C:/Users/yourname/.nanobot/workspace"
    }
  }
}
```

### 9.3 PowerShell 中的多行命令

PowerShell 使用 `` ` `` 作为续行符：

```powershell
curl http://127.0.0.1:8900/v1/chat/completions `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"messages":[{"role":"user","content":"hi"}]}'
```

### 9.4 Matrix 频道在 Windows 上不可用

`matrix-nio[e2e]` 依赖 `python-olm`，该库无 Windows 预编译包。如需使用 Matrix，请借助 WSL2 或使用 Linux/macOS。

### 9.5 Shell 沙箱（bwrap）在 Windows 上不可用

Bubblewrap 沙箱仅支持 Linux。Windows 上 `tools.exec.sandbox` 保持为空即可，exec 命令会直接执行（注意安全风险）。

### 9.6 WhatsApp Bridge 更新后需要重建

```bash
# 删除旧的 bridge 目录
rmdir /s /q %USERPROFILE%\.nanobot\bridge

# 重新登录
nanobot channels login whatsapp
```

---

## 十、项目文件位置（Windows）

| 内容 | 路径 |
|------|------|
| 配置文件 | `C:\Users\你的用户名\.nanobot\config.json` |
| Workspace | `C:\Users\你的用户名\.nanobot\workspace\` |
| 记忆文件 | `C:\Users\你的用户名\.nanobot\workspace\memory\` |
| 会话历史 | `C:\Users\你的用户名\.nanobot\workspace\sessions\` |
| Cron 任务 | `C:\Users\你的用户名\.nanobot\cron\` |

---

## 十一、开发相关

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest
```

### 代码检查

```bash
ruff check nanobot/
```

### 代码格式化

```bash
ruff format nanobot/
```

### Git 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 稳定版本 — Bug 修复和小改进 |
| `nightly` | 实验性功能 — 新特性和破坏性变更 |

新功能请提交到 `nightly` 分支，Bug 修复提交到 `main`。
